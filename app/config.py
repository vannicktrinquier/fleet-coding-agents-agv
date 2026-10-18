"""Runtime settings, read once when the app is created."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class FinePolicy:
    """How late returns are charged. All amounts are in cents."""

    grace_days: int = 3
    daily_cents: int = 25
    cap_cents: int = 1000


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path("library.db")
    admin_api_key: str = ""
    loan_days: int = 14
    max_active_loans: int = 5
    max_renewals: int = 2
    fine_block_cents: int = 500
    fines: FinePolicy = field(default_factory=FinePolicy)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        """Build settings from ``LIBRARY_*`` environment variables."""
        env = os.environ if environ is None else environ
        defaults = cls()
        policy = defaults.fines
        return cls(
            db_path=Path(env.get("LIBRARY_DB") or defaults.db_path),
            admin_api_key=env.get("LIBRARY_ADMIN_KEY", defaults.admin_api_key).strip(),
            loan_days=_env_int(env, "LIBRARY_LOAN_DAYS", defaults.loan_days, minimum=1),
            max_active_loans=_env_int(
                env, "LIBRARY_MAX_ACTIVE_LOANS", defaults.max_active_loans, minimum=1
            ),
            max_renewals=_env_int(
                env,
                "LIBRARY_MAX_RENEWALS",
                defaults.max_renewals,
            ),
            fine_block_cents=_env_int(env, "LIBRARY_FINE_BLOCK_CENTS", defaults.fine_block_cents),
            fines=FinePolicy(
                grace_days=_env_int(env, "LIBRARY_FINE_GRACE_DAYS", policy.grace_days),
                daily_cents=_env_int(env, "LIBRARY_FINE_DAILY_CENTS", policy.daily_cents),
                cap_cents=_env_int(env, "LIBRARY_FINE_CAP_CENTS", policy.cap_cents),
            ),
        )


def _env_int(env: Mapping[str, str], name: str, default: int, minimum: int = 0) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}")
    return value
