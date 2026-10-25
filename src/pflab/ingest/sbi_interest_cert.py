"""SBI deposit interest certificate PDF -> interest and TDS per account for one FY (PLAN S33).

The certificate ("interest ... paid by us on the TDR/STDR/SB/FCNR/Recurring A/Cs ... for the financial year
ended 31st March YYYY") lists one row per account: number, branch code, SB/FD, balance at 31 March, interest
paid, interest accrued, TDS, overhead TDS, currency; then a TOTAL row. For a cumulative FD the interest of
the year is paid + accrued (the bank "pays" out the TDS part). Rows must add up to the TOTAL row or the
certificate is refused. The PDF is password-protected; it is decrypted in memory by pypdf.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

TOL = 0.5

_FY = re.compile(r"year\s+ended\s+31st\s+March\s+(\d{4})", re.I)
_ROW = re.compile(r"^\s*(\d{9,})\s+(\d+)\s+(SB|FD|RD|TDR|STDR)\s+([\d,]+\.\d\d)\s+([\d,]+\.\d\d)\s+([\d,]+\.\d\d)\s+"
                  r"([\d,]+\.\d\d)\s+([\d,]+\.\d\d)\s+([A-Z]{3})\s*$", re.M)
_TOTAL = re.compile(r"^\s*TOTAL\s+([\d,]+\.\d\d)\s+([\d,]+\.\d\d)\s+([\d,]+\.\d\d)", re.M)


class CertificateError(ValueError):
    pass


@dataclass(frozen=True)
class Row:
    account: str
    kind: str
    balance: float
    paid: float
    accrued: float
    tds: float

    @property
    def fd_id(self) -> str:
        return self.account[-4:]


def _n(s: str) -> float:
    return float(s.replace(",", ""))


def parse_text(text: str) -> tuple:
    """-> (fy, rows). `fy` is the FY label (the year it ends)."""
    m = _FY.search(text)
    if not m:
        raise CertificateError("not an SBI interest certificate: no 'financial year ended 31st March'")
    rows = [Row(r[0], r[2], _n(r[3]), _n(r[4]), _n(r[5]), _n(r[6]) + _n(r[7])) for r in _ROW.findall(text)]
    if not rows:
        raise CertificateError("no account rows")
    t = _TOTAL.search(text)
    if not t:
        raise CertificateError("no TOTAL row")
    for name, got, want in (("interest paid", sum(r.paid for r in rows), _n(t[1])),
                            ("interest accrued", sum(r.accrued for r in rows), _n(t[2])),
                            ("TDS", sum(r.tds for r in rows), _n(t[3]))):
        if abs(got - want) > TOL:
            raise CertificateError(f"rows give {name} {got:,.2f}, the TOTAL row says {want:,.2f}")
    ids = [r.fd_id for r in rows if r.kind != "SB"]
    if len(set(ids)) != len(ids):
        raise CertificateError("two deposits share their last 4 digits: ids would collide")
    return int(m[1]), rows


def parse(path: Union[str, Path], password: Optional[str] = None) -> tuple:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(Path(path).read_bytes()))
    if r.is_encrypted and (not password or not r.decrypt(password)):
        raise CertificateError("the certificate is password-protected: pass the right password")
    return parse_text("\n".join(re.sub(r"[ \t]+", " ", pg.extract_text() or "") for pg in r.pages))


def fd_rows(rows: List[Row]) -> List[dict]:
    """The deposit rows in `pm.fd.save_interest` shape (SB interest comes from the bank statement instead)."""
    return [{"fd_id": r.fd_id, "paid": r.paid, "accrued": r.accrued, "tds": r.tds} for r in rows if r.kind != "SB"]
