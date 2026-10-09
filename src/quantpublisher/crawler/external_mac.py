"""외부 Mac mini 접속 계층 (SSH + rsync).

외부 Mac에는 아무것도 설치하지 않는다. 원본 DB는 항상 읽기 전용으로 연다
(`sqlite3 -readonly`). 원격에 쓰는 것은 이번 실행 전용 임시 디렉터리
(`mktemp -d`) 안의 중간 파일뿐이며, 가져온 뒤 `cleanup()`으로 지운다.

흐름:
    export_prices : 원격에서 종목별 daily 테이블을 PSV로 추출 -> rsync로 가져옴
    fetch_quant_db: 원격에서 quant.db를 .backup 스냅샷으로 복사 -> rsync로 가져옴

오류는 세 종류로 구분해서 상위로 전달한다 (조용히 넘기지 않는다).
    ExternalConnectionError: SSH 접속 실패 (꺼져 있음, 인증 실패, 타임아웃 등)
    ExternalCommandError   : 접속은 됐지만 원격 명령이 실패
    ExternalTransferError  : rsync 파일 전송 실패
"""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol

from config.settings import ExternalMacSettings
from quantpublisher.database.stock_code import STOCK_CODE_PATTERN

logger = logging.getLogger(__name__)

PRICES_FILE_NAME = "prices.psv"
FAILURES_FILE_NAME = "failures.psv"
QUANT_DB_FILE_NAME = "quant.db"

_SSH_CONNECT_FAILURE_EXIT_CODE = 255
_DEFAULT_TIMEOUT_SECONDS = 900
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REMOTE_TMP_DIR_RE = re.compile(r"^/[A-Za-z0-9_./-]*qp_(?:export|quant)\.[A-Za-z0-9]+$")

_SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=10")

# 원격에서 sh로 실행되는 가격 추출 스크립트 템플릿.
# 종목코드와 날짜는 Python에서 형식을 검증한 값만 heredoc으로 넣는다.
_EXPORT_SCRIPT = """\
set -u
STOCK_PRICE_DIR={stock_price_dir}
TMP=$(mktemp -d "${{TMPDIR:-/tmp}}/qp_export.XXXXXX") || exit 1
: > "$TMP/{prices_file}"
: > "$TMP/{failures_file}"
while IFS='|' read -r code since; do
  [ -n "$code" ] || continue
  db="$STOCK_PRICE_DIR/$code.db"
  if [ ! -f "$db" ]; then
    echo "$code|file not found" >> "$TMP/{failures_file}"
    continue
  fi
  if [ -n "$since" ]; then
    where="WHERE Time > '$since'"
  else
    where=""
  fi
  if sqlite3 -readonly -separator '|' "$db" \\
      "SELECT '$code', Time, open, high, low, close, volume FROM daily $where ORDER BY Time" \\
      > "$TMP/one.psv" 2> "$TMP/one.err" < /dev/null; then
    cat "$TMP/one.psv" >> "$TMP/{prices_file}"
  else
    echo "$code|$(tr '\\n' ' ' < "$TMP/one.err")" >> "$TMP/{failures_file}"
  fi
done <<'QP_SINCE_EOF'
{since_lines}
QP_SINCE_EOF
rm -f "$TMP/one.psv" "$TMP/one.err"
echo "$TMP"
"""

_QUANT_SCRIPT = """\
set -u
TMP=$(mktemp -d "${{TMPDIR:-/tmp}}/qp_quant.XXXXXX") || exit 1
if ! sqlite3 -readonly {quant_db_path} ".backup '$TMP/{quant_file}'"; then
  rm -rf "$TMP"
  exit 1
fi
echo "$TMP"
"""


class ExternalSourceError(Exception):
    """외부 Mac 접근 중 발생한 오류의 공통 부모."""


class ExternalConnectionError(ExternalSourceError):
    """SSH 접속 실패."""


class ExternalCommandError(ExternalSourceError):
    """원격 명령 실행 실패."""


class ExternalTransferError(ExternalSourceError):
    """rsync 파일 전송 실패."""


@dataclass(frozen=True, slots=True)
class PriceExport:
    """가격 추출 결과 파일.

    Attributes:
        psv_path: `종목코드|Time|open|high|low|close|volume` 행이 담긴 파일.
        failures: 추출에 실패한 종목코드 -> 원인 메시지.
    """

    psv_path: Path
    failures: dict[str, str]


class ExternalDataSource(Protocol):
    """수집기가 의존하는 외부 데이터 소스 인터페이스 (테스트에서 대체 가능)."""

    def list_price_stock_codes(self) -> list[str]: ...

    def export_prices(self, since_by_code: Mapping[str, str | None], dest_dir: Path) -> PriceExport: ...

    def fetch_quant_db(self, dest_dir: Path) -> Path: ...


Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class ExternalMacClient:
    """SSH/rsync로 외부 Mac의 DB를 읽어 오는 클라이언트.

    Args:
        config: 접속 설정 (호스트, 사용자, 원격 경로).
        runner: subprocess.run 호환 호출 대상. 테스트에서 가짜로 교체한다.
        timeout_seconds: 개별 SSH/rsync 호출의 제한 시간.
    """

    def __init__(
        self,
        config: ExternalMacSettings,
        runner: Runner = subprocess.run,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._config = config
        self._runner = runner
        self._timeout = timeout_seconds

    @property
    def _target(self) -> str:
        if self._config.user:
            return f"{self._config.user}@{self._config.host}"
        return self._config.host

    # ── 공개 API ────────────────────────────────────────────────────────

    def list_price_stock_codes(self) -> list[str]:
        """원격 stock-price 디렉터리에 있는 <종목코드>.db의 종목코드 목록."""
        command = f"ls -1 {shlex.quote(self._config.stock_price_dir)}"
        output = self._ssh(command)
        codes = []
        for line in output.splitlines():
            name = line.strip()
            if name.endswith(".db") and STOCK_CODE_PATTERN.match(name[:-3]):
                codes.append(name[:-3])
        return sorted(codes)

    def export_prices(
        self, since_by_code: Mapping[str, str | None], dest_dir: Path
    ) -> PriceExport:
        """종목별 daily 테이블을 원격에서 추출해 dest_dir로 가져온다.

        Args:
            since_by_code: 종목코드 -> 이 날짜 '이후'만 가져올 기준일.
                None이면 해당 종목은 전체를 가져온다 (최초 백필).
            dest_dir: 로컬 저장 디렉터리 (없으면 만든다).
        """
        script = _EXPORT_SCRIPT.format(
            stock_price_dir=shlex.quote(self._config.stock_price_dir),
            prices_file=PRICES_FILE_NAME,
            failures_file=FAILURES_FILE_NAME,
            since_lines=_render_since_lines(since_by_code),
        )
        remote_tmp = self._run_script(script)
        try:
            self._rsync_pull(remote_tmp, dest_dir)
        finally:
            self.cleanup(remote_tmp)
        failures = _read_failures(dest_dir / FAILURES_FILE_NAME)
        return PriceExport(psv_path=dest_dir / PRICES_FILE_NAME, failures=failures)

    def fetch_quant_db(self, dest_dir: Path) -> Path:
        """원격 quant.db를 .backup 스냅샷으로 만들어 dest_dir로 가져온다."""
        script = _QUANT_SCRIPT.format(
            quant_db_path=shlex.quote(self._config.quant_db_path),
            quant_file=QUANT_DB_FILE_NAME,
        )
        remote_tmp = self._run_script(script)
        try:
            self._rsync_pull(remote_tmp, dest_dir)
        finally:
            self.cleanup(remote_tmp)
        return dest_dir / QUANT_DB_FILE_NAME

    def cleanup(self, remote_tmp: str) -> None:
        """이번 실행이 만든 원격 임시 디렉터리를 지운다.

        경로 형식이 우리가 만든 것(qp_export.* / qp_quant.*)이 아니면 지우지 않는다.
        정리 실패는 이미 가져온 데이터를 무효로 만들지 않으므로 경고만 남긴다.
        """
        if not _REMOTE_TMP_DIR_RE.match(remote_tmp):
            logger.warning("external_cleanup_skipped unexpected_path=%s", remote_tmp)
            return
        try:
            self._ssh(f"rm -rf -- {shlex.quote(remote_tmp)}")
        except ExternalSourceError as exc:
            logger.warning("external_cleanup_failed path=%s error=%s", remote_tmp, exc)

    # ── 내부 구현 ───────────────────────────────────────────────────────

    def _run_script(self, script: str) -> str:
        """스크립트를 원격 sh의 stdin으로 실행하고, 마지막 줄(임시 디렉터리)을 반환한다."""
        output = self._ssh("sh -s", stdin=script)
        lines = [line for line in output.splitlines() if line.strip()]
        if not lines or not _REMOTE_TMP_DIR_RE.match(lines[-1].strip()):
            raise ExternalCommandError(f"원격 스크립트가 임시 디렉터리 경로를 반환하지 않았습니다: {output!r}")
        return lines[-1].strip()

    def _ssh(self, remote_command: str, stdin: str | None = None) -> str:
        args = ["ssh", *_SSH_OPTIONS, self._target, remote_command]
        logger.info("external_ssh target=%s command=%s", self._target, remote_command.split()[0])
        try:
            result = self._runner(
                args, input=stdin, capture_output=True, text=True, timeout=self._timeout
            )
        except subprocess.TimeoutExpired as exc:
            raise ExternalConnectionError(
                f"SSH 응답 시간 초과 ({self._timeout}s): {self._target}"
            ) from exc
        except FileNotFoundError as exc:
            raise ExternalConnectionError("ssh 실행 파일을 찾을 수 없습니다.") from exc
        if result.returncode == _SSH_CONNECT_FAILURE_EXIT_CODE:
            raise ExternalConnectionError(
                f"SSH 접속 실패: {self._target}: {result.stderr.strip()}"
            )
        if result.returncode != 0:
            raise ExternalCommandError(
                f"원격 명령 실패 (exit={result.returncode}): {result.stderr.strip()}"
            )
        return result.stdout

    def _rsync_pull(self, remote_dir: str, dest_dir: Path) -> None:
        dest_dir.mkdir(parents=True, exist_ok=True)
        ssh_command = " ".join(["ssh", *_SSH_OPTIONS])
        args = [
            "rsync",
            "-a",
            "-e",
            ssh_command,
            f"{self._target}:{remote_dir}/",
            f"{dest_dir}/",
        ]
        logger.info("external_rsync target=%s dest=%s", self._target, dest_dir)
        try:
            result = self._runner(args, capture_output=True, text=True, timeout=self._timeout)
        except subprocess.TimeoutExpired as exc:
            raise ExternalTransferError(f"rsync 시간 초과 ({self._timeout}s)") from exc
        except FileNotFoundError as exc:
            raise ExternalTransferError("rsync 실행 파일을 찾을 수 없습니다.") from exc
        if result.returncode != 0:
            raise ExternalTransferError(
                f"rsync 실패 (exit={result.returncode}): {result.stderr.strip()}"
            )


def _render_since_lines(since_by_code: Mapping[str, str | None]) -> str:
    """heredoc에 넣을 `종목코드|기준일` 줄을 만든다. 형식이 틀린 값은 거부한다."""
    lines = []
    for code in sorted(since_by_code):
        since = since_by_code[code]
        if not STOCK_CODE_PATTERN.match(code):
            raise ValueError(f"잘못된 종목코드: {code!r}")
        if since is not None and not _DATE_RE.match(since):
            raise ValueError(f"잘못된 기준일 형식 (YYYY-MM-DD 필요): {code} {since!r}")
        lines.append(f"{code}|{since or ''}")
    return "\n".join(lines)


def _read_failures(path: Path) -> dict[str, str]:
    """failures.psv(`종목코드|메시지`)를 읽는다. 파일이 없으면 빈 dict."""
    if not path.exists():
        return {}
    failures: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        code, _, message = line.partition("|")
        if code.strip():
            failures[code.strip()] = message.strip()
    return failures
