"""Generate realistic, fully synthetic spreadsheets (CSV + XLSX) and a split manifest.

All names, organizations, locations and values are invented from synthetic vocabularies
using a fixed random seed — no real or personal data is used.

CLI usage:
    uv run python -m src.data.sheets
    uv run python -m src.data.sheets --seed 42 --out-dir data/sheets
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import openpyxl
import pandas as pd
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from formulalm.config import REPO_ROOT, load_config
from formulalm.logging_utils import get_logger

ColumnType = Literal["text", "integer", "decimal", "date", "category"]

FIXED_XLSX_TIMESTAMP = datetime(2026, 11, 24, 0, 0, 0)
DEFAULT_MIN_ROWS = 30
DEFAULT_MAX_ROWS = 200
DEFAULT_BLANK_RATE = 0.04
DEFAULT_HELDOUT_FRACTION = 0.2

# ---------------------------------------------------------------------------
# Purely invented synthetic vocabularies (no real people, companies or cities)
# ---------------------------------------------------------------------------

_FIRST_NAMES = (
    "Aelen",
    "Bram",
    "Cira",
    "Dorian",
    "Elara",
    "Fenn",
    "Galia",
    "Halen",
    "Iona",
    "Joren",
    "Kaelen",
    "Lira",
    "Maren",
    "Nolan",
    "Orin",
    "Pira",
    "Quen",
    "Rina",
    "Soren",
    "Talia",
    "Ulan",
    "Vesper",
    "Wren",
    "Yara",
    "Zev",
    "Caden",
    "Eris",
    "Kova",
    "Lumen",
    "Tovin",
    "Nira",
    "Rovan",
)

_LAST_NAMES = (
    "Vorn",
    "Brek",
    "Meld",
    "Halv",
    "Kest",
    "Palk",
    "Vess",
    "Tov",
    "Neld",
    "Fask",
    "Dren",
    "Solk",
    "Bramm",
    "Corv",
    "Hald",
    "Jern",
    "Korr",
    "Lisk",
    "Morn",
    "Norr",
    "Oren",
    "Pell",
    "Quill",
    "Rask",
    "Stel",
    "Tarn",
    "Usk",
    "Vald",
    "Wesk",
    "Yorn",
    "Zell",
    "Drav",
)

_ORG_PREFIXES = (
    "Vektor",
    "Bramble",
    "Solstice",
    "Kestrel",
    "Cinder",
    "Helios",
    "Marlin",
    "Quarry",
    "Trellis",
    "Osprey",
    "Cobalt",
    "Linden",
    "Aether",
    "Boreal",
    "Copper",
    "Drifter",
    "Fathom",
    "Glimmer",
    "Harbor",
    "Ivory",
)

_ORG_SUFFIXES = (
    "Supply",
    "Goods",
    "Systems",
    "Logistics",
    "Works",
    "Craft",
    "Tools",
    "Labs",
    "Freight",
    "Devices",
    "Apparel",
    "Studio",
    "Foods",
    "Metals",
)

_CITIES = (
    "Ashvale",
    "Brinport",
    "Suncroft",
    "Mirehaven",
    "Larkspur",
    "Crestholm",
    "Veldor",
    "Fallowby",
    "Duskford",
    "Stonewick",
)

_ITEMS = (
    "Thermal Flask",
    "Desk Lamp Pro",
    "Foldable Stand",
    "Canvas Pack",
    "Ceramic Mug",
    "Steel Ruler",
    "Travel Pouch",
    "Docking Hub",
    "Mesh Chair",
    "Task Notebook",
    "Cable Sleeve",
    "Monitor Riser",
    "Pocket Scale",
    "Label Printer",
    "Storage Crate",
    "Acoustic Panel",
    "Clamp Light",
    "Drafting Pad",
    "Battery Pack",
    "Barcode Wand",
)

_PARTS = (
    "Hex Flange Bolt",
    "Brass Coupler",
    "Nylon Washer",
    "Gear Pinion",
    "Torque Spring",
    "Rubber Gasket",
    "Steel Bushing",
    "Linear Bearing",
    "Valve Collar",
    "Rivet Sleeve",
    "Shaft Key",
    "Guide Rail",
    "Seal Ring",
    "Anchor Bracket",
    "Cable Gland",
    "Pivot Pin",
)

_PROJECTS = (
    "Atlas Revamp",
    "Beacon Sync",
    "Cedar Portal",
    "Delta Ledger",
    "Echo Pipeline",
    "Fjord Mobile",
    "Granite Core",
    "Harbor Auth",
    "Indigo Search",
    "Juniper Billing",
    "Kite Analytics",
    "Lantern Docs",
)

_TASKS = (
    "Audit schema rules",
    "Refactor parser",
    "Add retry guard",
    "Verify CSV export",
    "Tune cache window",
    "Draft API spec",
    "Patch date filter",
    "Clean stale logs",
    "Build status chart",
    "Review access roles",
    "Fix rounding bug",
    "Test bulk import",
)

_CAMPAIGNS = (
    "Autumn Launch",
    "Q1 Awareness",
    "Partner Push",
    "Starter Bundle",
    "Winter Promo",
    "Demo Webinar",
    "Feature Drop",
    "Referral Drive",
    "Spring Refresh",
    "Annual Upgrade",
    "Trial Nudge",
    "Holiday Flash",
)

_NOTES = (
    "Verified receipt",
    "Pending signoff",
    "Standard rate",
    "Recurring bill",
    "Checked by ops",
    "Urgent review",
    "Budget matched",
    "Split invoice",
)


def _invented_person(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"


def _invented_org(rng: random.Random) -> str:
    return f"{rng.choice(_ORG_PREFIXES)} {rng.choice(_ORG_SUFFIXES)}"


def _random_date(rng: random.Random, start: date, end: date) -> date:
    span = (end - start).days
    return start + timedelta(days=rng.randint(0, span))


def _code_gen(
    prefix: str, start: int = 1001, width: int = 4
) -> Callable[[random.Random, int], str]:
    def _gen(_rng: random.Random, row_idx: int) -> str:
        return f"{prefix}-{start + row_idx:0{width}d}"

    return _gen


def _text_choice(pool: tuple[str, ...]) -> Callable[[random.Random, int], str]:
    def _gen(rng: random.Random, _row_idx: int) -> str:
        return rng.choice(pool)

    return _gen


def _person_gen() -> Callable[[random.Random, int], str]:
    def _gen(rng: random.Random, _row_idx: int) -> str:
        return _invented_person(rng)

    return _gen


def _org_gen() -> Callable[[random.Random, int], str]:
    def _gen(rng: random.Random, _row_idx: int) -> str:
        return _invented_org(rng)

    return _gen


def _int_gen(low: int, high: int) -> Callable[[random.Random, int], int]:
    def _gen(rng: random.Random, _row_idx: int) -> int:
        return rng.randint(low, high)

    return _gen


def _dec_gen(low: float, high: float, decimals: int = 2) -> Callable[[random.Random, int], float]:
    def _gen(rng: random.Random, _row_idx: int) -> float:
        return round(rng.uniform(low, high), decimals)

    return _gen


def _date_gen(start: date, end: date) -> Callable[[random.Random, int], date]:
    def _gen(rng: random.Random, _row_idx: int) -> date:
        return _random_date(rng, start, end)

    return _gen


def _cat_gen(categories: tuple[str, ...]) -> Callable[[random.Random, int], str]:
    def _gen(rng: random.Random, _row_idx: int) -> str:
        return rng.choice(categories)

    return _gen


@dataclass(frozen=True)
class ColumnSpec:
    """Definition of one column in a synthetic spreadsheet."""

    name: str
    col_type: ColumnType
    generator: Callable[[random.Random, int], Any]
    nullable: bool = False
    unique: bool = False
    categories: tuple[str, ...] = ()


@dataclass(frozen=True)
class SheetSpec:
    """Schema blueprint for one synthetic spreadsheet."""

    sheet_id: str
    domain: str
    description: str
    columns: tuple[ColumnSpec, ...]
    key_column_index: int = 0
    tags: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# 25 synthetic spreadsheet schemas across 11 domains (5 to 8 columns each)
# ---------------------------------------------------------------------------


def build_sheet_specs() -> list[SheetSpec]:
    """Return the 25 synthetic spreadsheet blueprints covering 11 business domains."""
    d_2025_start = date(2025, 1, 1)
    d_2026_mid = date(2026, 6, 30)
    d_2020_start = date(2020, 1, 1)
    d_2025_end = date(2025, 12, 31)

    return [
        # --- 1. sales (3 sheets) ---
        SheetSpec(
            sheet_id="sales_regional_q1",
            domain="sales",
            description="Regional product sales transactions by rep and product line.",
            columns=(
                ColumnSpec("Sale ID", "text", _code_gen("SL"), unique=True),
                ColumnSpec("Order Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec(
                    "Region",
                    "category",
                    _cat_gen(("North", "South", "East", "West", "Central")),
                    categories=("North", "South", "East", "West", "Central"),
                ),
                ColumnSpec("Sales Rep", "text", _person_gen()),
                ColumnSpec(
                    "Product Line",
                    "category",
                    _cat_gen(("Hardware", "Accessories", "Furniture", "Supplies")),
                    categories=("Hardware", "Accessories", "Furniture", "Supplies"),
                ),
                ColumnSpec("Units Sold", "integer", _int_gen(1, 80)),
                ColumnSpec("Unit Price", "decimal", _dec_gen(12.5, 450.0), nullable=True),
            ),
        ),
        SheetSpec(
            sheet_id="sales_retail_store",
            domain="sales",
            description="Point-of-sale retail store receipts across branches.",
            columns=(
                ColumnSpec("Receipt Code", "text", _code_gen("RC"), unique=True),
                ColumnSpec("Sale Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec(
                    "Store Branch",
                    "category",
                    _cat_gen(_CITIES[:5]),
                    categories=_CITIES[:5],
                ),
                ColumnSpec("Item Name", "text", _text_choice(_ITEMS), nullable=True),
                ColumnSpec("Quantity", "integer", _int_gen(1, 25)),
                ColumnSpec("Net Amount", "decimal", _dec_gen(8.0, 920.0)),
            ),
        ),
        SheetSpec(
            sheet_id="sales_b2b_deals",
            domain="sales",
            description="B2B sales pipeline deals with contract value and discount.",
            columns=(
                ColumnSpec("Deal ID", "text", _code_gen("DL"), unique=True),
                ColumnSpec("Close Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec("Account Name", "text", _org_gen()),
                ColumnSpec(
                    "Territory",
                    "category",
                    _cat_gen(("North", "South", "East", "West")),
                    categories=("North", "South", "East", "West"),
                ),
                ColumnSpec(
                    "Stage",
                    "category",
                    _cat_gen(("Won", "Proposal", "Negotiation", "Lost")),
                    categories=("Won", "Proposal", "Negotiation", "Lost"),
                ),
                ColumnSpec("Seats", "integer", _int_gen(5, 250)),
                ColumnSpec("Contract Value", "decimal", _dec_gen(1500.0, 48000.0)),
                ColumnSpec("Discount Pct", "decimal", _dec_gen(0.0, 0.25), nullable=True),
            ),
        ),
        # --- 2. hr_employees (3 sheets) ---
        SheetSpec(
            sheet_id="hr_employee_roster",
            domain="hr_employees",
            description="Company employee directory with departments, tenure and salaries.",
            columns=(
                ColumnSpec("Employee ID", "text", _code_gen("EMP"), unique=True),
                ColumnSpec("Full Name", "text", _person_gen()),
                ColumnSpec(
                    "Department",
                    "category",
                    _cat_gen(("Engineering", "Operations", "Finance", "Design", "Support")),
                    categories=("Engineering", "Operations", "Finance", "Design", "Support"),
                ),
                ColumnSpec(
                    "Work Hub",
                    "category",
                    _cat_gen(_CITIES[5:]),
                    categories=_CITIES[5:],
                ),
                ColumnSpec("Hire Date", "date", _date_gen(d_2020_start, d_2025_end)),
                ColumnSpec("Years Service", "integer", _int_gen(0, 12)),
                ColumnSpec("Annual Salary", "decimal", _dec_gen(38000.0, 145000.0), nullable=True),
            ),
        ),
        SheetSpec(
            sheet_id="hr_payroll_ledger",
            domain="hr_employees",
            description="Monthly payroll hours, hourly rates and bonus payouts.",
            columns=(
                ColumnSpec("Payslip ID", "text", _code_gen("PAY"), unique=True),
                ColumnSpec("Staff Name", "text", _person_gen()),
                ColumnSpec("Pay Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec(
                    "Role Band",
                    "category",
                    _cat_gen(("Junior", "Mid", "Senior", "Lead")),
                    categories=("Junior", "Mid", "Senior", "Lead"),
                ),
                ColumnSpec("Hours Worked", "integer", _int_gen(120, 195)),
                ColumnSpec("Hourly Rate", "decimal", _dec_gen(18.0, 85.0)),
                ColumnSpec("Bonus Amount", "decimal", _dec_gen(0.0, 2500.0), nullable=True),
            ),
        ),
        SheetSpec(
            sheet_id="hr_performance_reviews",
            domain="hr_employees",
            description="Annual staff performance review scores and goals completed.",
            columns=(
                ColumnSpec("Review ID", "text", _code_gen("REV"), unique=True),
                ColumnSpec("Employee Name", "text", _person_gen()),
                ColumnSpec(
                    "Team",
                    "category",
                    _cat_gen(("Platform", "Data", "Growth", "Security", "QA")),
                    categories=("Platform", "Data", "Growth", "Security", "QA"),
                ),
                ColumnSpec("Review Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec("Goals Met", "integer", _int_gen(1, 10)),
                ColumnSpec("Review Score", "decimal", _dec_gen(2.0, 5.0), nullable=True),
            ),
        ),
        # --- 3. inventory (3 sheets) ---
        SheetSpec(
            sheet_id="inventory_warehouse_stock",
            domain="inventory",
            description="Warehouse stock quantities, reorder thresholds and unit costs.",
            columns=(
                ColumnSpec("SKU", "text", _code_gen("SKU"), unique=True),
                ColumnSpec("Item Description", "text", _text_choice(_ITEMS)),
                ColumnSpec(
                    "Warehouse",
                    "category",
                    _cat_gen(("WH-North", "WH-South", "WH-East", "WH-Central")),
                    categories=("WH-North", "WH-South", "WH-East", "WH-Central"),
                ),
                ColumnSpec("Stock Qty", "integer", _int_gen(0, 600)),
                ColumnSpec("Reorder Level", "integer", _int_gen(15, 120), nullable=True),
                ColumnSpec("Unit Cost", "decimal", _dec_gen(4.5, 210.0)),
                ColumnSpec("Last Restocked", "date", _date_gen(d_2025_start, d_2026_mid)),
            ),
        ),
        SheetSpec(
            sheet_id="inventory_parts_catalog",
            domain="inventory",
            description="Compact spare parts inventory with supplier tier and bin weight.",
            columns=(
                ColumnSpec("Part Code", "text", _code_gen("PRT"), unique=True),
                ColumnSpec(
                    "Supplier Tier",
                    "category",
                    _cat_gen(("Tier 1", "Tier 2", "Tier 3")),
                    categories=("Tier 1", "Tier 2", "Tier 3"),
                ),
                ColumnSpec("Bin Count", "integer", _int_gen(5, 450)),
                ColumnSpec("Unit Weight", "decimal", _dec_gen(0.15, 14.8), nullable=True),
                ColumnSpec("Inspection Date", "date", _date_gen(d_2025_start, d_2026_mid)),
            ),
        ),
        SheetSpec(
            sheet_id="inventory_stock_movements",
            domain="inventory",
            description="Inbound and outbound warehouse stock movement ledger.",
            columns=(
                ColumnSpec("Move ID", "text", _code_gen("MOV"), unique=True),
                ColumnSpec("Move Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec("Part Name", "text", _text_choice(_PARTS)),
                ColumnSpec(
                    "Movement Type",
                    "category",
                    _cat_gen(("Inbound", "Outbound", "Transfer", "Adjustment")),
                    categories=("Inbound", "Outbound", "Transfer", "Adjustment"),
                ),
                ColumnSpec(
                    "Zone",
                    "category",
                    _cat_gen(("Zone A", "Zone B", "Zone C", "Cold Bay")),
                    categories=("Zone A", "Zone B", "Zone C", "Cold Bay"),
                ),
                ColumnSpec("Units Moved", "integer", _int_gen(1, 200)),
                ColumnSpec("Valuation", "decimal", _dec_gen(25.0, 9500.0), nullable=True),
            ),
        ),
        # --- 4. student_grades (3 sheets) ---
        SheetSpec(
            sheet_id="grades_course_scores",
            domain="student_grades",
            description="Course exam scores and completed assignments by subject.",
            columns=(
                ColumnSpec("Student ID", "text", _code_gen("STU"), unique=True),
                ColumnSpec("Student Name", "text", _person_gen()),
                ColumnSpec(
                    "Subject",
                    "category",
                    _cat_gen(("Math", "Physics", "Computing", "Economics", "History")),
                    categories=("Math", "Physics", "Computing", "Economics", "History"),
                ),
                ColumnSpec(
                    "Section",
                    "category",
                    _cat_gen(("Sec A", "Sec B", "Sec C")),
                    categories=("Sec A", "Sec B", "Sec C"),
                ),
                ColumnSpec("Exam Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec("Assignments Done", "integer", _int_gen(0, 12)),
                ColumnSpec("Final Score", "decimal", _dec_gen(35.0, 100.0), nullable=True),
            ),
        ),
        SheetSpec(
            sheet_id="grades_semester_summary",
            domain="student_grades",
            description="Compact semester GPA and credit hours per student.",
            columns=(
                ColumnSpec("Roll No", "text", _code_gen("RL"), unique=True),
                ColumnSpec(
                    "Major",
                    "category",
                    _cat_gen(("Computer Science", "Data Science", "Mathematics", "Physics")),
                    categories=("Computer Science", "Data Science", "Mathematics", "Physics"),
                ),
                ColumnSpec("Credits", "integer", _int_gen(9, 21)),
                ColumnSpec("Semester GPA", "decimal", _dec_gen(1.8, 4.0), nullable=True),
                ColumnSpec("Term End", "date", _date_gen(d_2025_start, d_2026_mid)),
            ),
        ),
        SheetSpec(
            sheet_id="grades_lab_assessments",
            domain="student_grades",
            description="Lab submission attempts, earned points and grading status.",
            columns=(
                ColumnSpec("Submission ID", "text", _code_gen("LAB"), unique=True),
                ColumnSpec("Candidate", "text", _person_gen()),
                ColumnSpec(
                    "Lab Module",
                    "category",
                    _cat_gen(("SQL", "Python", "Networks", "Statistics", "Systems")),
                    categories=("SQL", "Python", "Networks", "Statistics", "Systems"),
                ),
                ColumnSpec("Submit Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec("Attempts", "integer", _int_gen(1, 5)),
                ColumnSpec("Points Earned", "decimal", _dec_gen(10.0, 50.0), nullable=True),
                ColumnSpec(
                    "Status",
                    "category",
                    _cat_gen(("Passed", "Needs Review", "Failed")),
                    categories=("Passed", "Needs Review", "Failed"),
                ),
            ),
        ),
        # --- 5. expenses (3 sheets) ---
        SheetSpec(
            sheet_id="expenses_travel_claims",
            domain="expenses",
            description="Employee travel reimbursement claims by city and category.",
            columns=(
                ColumnSpec("Claim ID", "text", _code_gen("CLM"), unique=True),
                ColumnSpec("Expense Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec("Claimant", "text", _person_gen()),
                ColumnSpec(
                    "Category",
                    "category",
                    _cat_gen(("Flight", "Hotel", "Meals", "Transit", "Conference")),
                    categories=("Flight", "Hotel", "Meals", "Transit", "Conference"),
                ),
                ColumnSpec(
                    "City",
                    "category",
                    _cat_gen(_CITIES[:6]),
                    categories=_CITIES[:6],
                ),
                ColumnSpec("Nights", "integer", _int_gen(0, 10), nullable=True),
                ColumnSpec("Amount USD", "decimal", _dec_gen(15.0, 2400.0)),
            ),
        ),
        SheetSpec(
            sheet_id="expenses_department_spend",
            domain="expenses",
            description="Departmental vendor spend vouchers across cost centers.",
            columns=(
                ColumnSpec("Voucher No", "text", _code_gen("VCH"), unique=True),
                ColumnSpec("Posted Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec(
                    "Cost Center",
                    "category",
                    _cat_gen(("IT", "Facilities", "Marketing", "People", "Legal")),
                    categories=("IT", "Facilities", "Marketing", "People", "Legal"),
                ),
                ColumnSpec("Vendor Name", "text", _org_gen()),
                ColumnSpec("Invoice Items", "integer", _int_gen(1, 40)),
                ColumnSpec("Total Spend", "decimal", _dec_gen(75.0, 18500.0), nullable=True),
            ),
        ),
        SheetSpec(
            sheet_id="expenses_office_bills",
            domain="expenses",
            description="Recurring facility utility and operations bills.",
            columns=(
                ColumnSpec("Bill ID", "text", _code_gen("BIL"), unique=True),
                ColumnSpec("Due Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec(
                    "Facility",
                    "category",
                    _cat_gen(("HQ North", "Annex East", "Depot West", "Lab South")),
                    categories=("HQ North", "Annex East", "Depot West", "Lab South"),
                ),
                ColumnSpec(
                    "Expense Type",
                    "category",
                    _cat_gen(("Electricity", "Internet", "Water", "Maintenance", "Security")),
                    categories=("Electricity", "Internet", "Water", "Maintenance", "Security"),
                ),
                ColumnSpec("Utility Units", "integer", _int_gen(10, 1200)),
                ColumnSpec("Bill Amount", "decimal", _dec_gen(45.0, 4200.0)),
                ColumnSpec("Approval Note", "text", _text_choice(_NOTES), nullable=True),
            ),
        ),
        # --- 6. orders (3 sheets) ---
        SheetSpec(
            sheet_id="orders_ecommerce",
            domain="orders",
            description="Online customer orders with channel, fulfillment status and shipping.",
            columns=(
                ColumnSpec("Order ID", "text", _code_gen("ORD"), unique=True),
                ColumnSpec("Order Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec("Customer Name", "text", _person_gen()),
                ColumnSpec(
                    "Channel",
                    "category",
                    _cat_gen(("Web", "Mobile App", "Marketplace", "Phone")),
                    categories=("Web", "Mobile App", "Marketplace", "Phone"),
                ),
                ColumnSpec(
                    "Fulfillment",
                    "category",
                    _cat_gen(("Delivered", "Shipped", "Pending", "Cancelled")),
                    categories=("Delivered", "Shipped", "Pending", "Cancelled"),
                ),
                ColumnSpec("Item Count", "integer", _int_gen(1, 15)),
                ColumnSpec("Order Total", "decimal", _dec_gen(14.0, 1250.0)),
                ColumnSpec("Shipping Fee", "decimal", _dec_gen(0.0, 35.0), nullable=True),
            ),
        ),
        SheetSpec(
            sheet_id="orders_wholesale_shipments",
            domain="orders",
            description="Wholesale carton shipments by region and priority.",
            columns=(
                ColumnSpec("Shipment ID", "text", _code_gen("SHP"), unique=True),
                ColumnSpec("Ship Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec("Buyer Org", "text", _org_gen()),
                ColumnSpec(
                    "Region",
                    "category",
                    _cat_gen(("North", "South", "East", "West")),
                    categories=("North", "South", "East", "West"),
                ),
                ColumnSpec("Cartons", "integer", _int_gen(2, 180)),
                ColumnSpec("Freight Cost", "decimal", _dec_gen(80.0, 6400.0), nullable=True),
                ColumnSpec(
                    "Priority",
                    "category",
                    _cat_gen(("Standard", "Express", "Economy")),
                    categories=("Standard", "Express", "Economy"),
                ),
            ),
        ),
        SheetSpec(
            sheet_id="orders_purchase_requests",
            domain="orders",
            description="Procurement purchase orders placed with external suppliers.",
            columns=(
                ColumnSpec("PO Number", "text", _code_gen("PO"), unique=True),
                ColumnSpec("Request Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec("Vendor", "text", _org_gen()),
                ColumnSpec(
                    "Category",
                    "category",
                    _cat_gen(("Raw Material", "Packaging", "Equipment", "Software")),
                    categories=("Raw Material", "Packaging", "Equipment", "Software"),
                ),
                ColumnSpec("Order Qty", "integer", _int_gen(5, 500)),
                ColumnSpec("Unit Price", "decimal", _dec_gen(6.0, 380.0), nullable=True),
            ),
        ),
        # --- 7. project_tracking (2 sheets) ---
        SheetSpec(
            sheet_id="projects_task_board",
            domain="project_tracking",
            description="Engineering task board with assignees, points and due dates.",
            columns=(
                ColumnSpec("Task ID", "text", _code_gen("TSK"), unique=True),
                ColumnSpec("Task Title", "text", _text_choice(_TASKS)),
                ColumnSpec("Assignee", "text", _person_gen(), nullable=True),
                ColumnSpec(
                    "Workstream",
                    "category",
                    _cat_gen(("Backend", "Frontend", "Infra", "ML", "Docs")),
                    categories=("Backend", "Frontend", "Infra", "ML", "Docs"),
                ),
                ColumnSpec(
                    "Status",
                    "category",
                    _cat_gen(("Done", "In Progress", "Blocked", "Backlog")),
                    categories=("Done", "In Progress", "Blocked", "Backlog"),
                ),
                ColumnSpec("Story Points", "integer", _int_gen(1, 13)),
                ColumnSpec("Due Date", "date", _date_gen(d_2025_start, d_2026_mid)),
            ),
        ),
        SheetSpec(
            sheet_id="projects_sprint_budget",
            domain="project_tracking",
            description="Sprint time logs, billable hourly rates and budget spend.",
            columns=(
                ColumnSpec("Entry ID", "text", _code_gen("LOG"), unique=True),
                ColumnSpec("Log Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec("Project Name", "text", _text_choice(_PROJECTS)),
                ColumnSpec(
                    "Phase",
                    "category",
                    _cat_gen(("Discovery", "Build", "Testing", "Launch")),
                    categories=("Discovery", "Build", "Testing", "Launch"),
                ),
                ColumnSpec("Hours Logged", "integer", _int_gen(2, 60)),
                ColumnSpec("Billable Rate", "decimal", _dec_gen(45.0, 165.0)),
                ColumnSpec("Budget Used", "decimal", _dec_gen(200.0, 9500.0), nullable=True),
            ),
        ),
        # --- 8. attendance (2 sheets) ---
        SheetSpec(
            sheet_id="attendance_daily_log",
            domain="attendance",
            description="Daily staff attendance records and hours present.",
            columns=(
                ColumnSpec("Record ID", "text", _code_gen("ATT"), unique=True),
                ColumnSpec("Work Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec("Member Name", "text", _person_gen()),
                ColumnSpec(
                    "Department",
                    "category",
                    _cat_gen(("Engineering", "Support", "Operations", "Sales")),
                    categories=("Engineering", "Support", "Operations", "Sales"),
                ),
                ColumnSpec(
                    "Attendance Status",
                    "category",
                    _cat_gen(("Present", "Remote", "Leave", "Absent")),
                    categories=("Present", "Remote", "Leave", "Absent"),
                ),
                ColumnSpec("Hours Present", "decimal", _dec_gen(0.0, 10.5), nullable=True),
            ),
        ),
        SheetSpec(
            sheet_id="attendance_shift_records",
            domain="attendance",
            description="Operations shift check-ins with late minutes and overtime hours.",
            columns=(
                ColumnSpec("Shift ID", "text", _code_gen("SHF"), unique=True),
                ColumnSpec("Shift Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec("Operator", "text", _person_gen()),
                ColumnSpec(
                    "Site",
                    "category",
                    _cat_gen(("Site Alpha", "Site Beta", "Site Gamma")),
                    categories=("Site Alpha", "Site Beta", "Site Gamma"),
                ),
                ColumnSpec(
                    "Shift Type",
                    "category",
                    _cat_gen(("Morning", "Evening", "Night")),
                    categories=("Morning", "Evening", "Night"),
                ),
                ColumnSpec("Late Minutes", "integer", _int_gen(0, 45)),
                ColumnSpec("Overtime Hours", "decimal", _dec_gen(0.0, 4.5), nullable=True),
            ),
        ),
        # --- 9. subscriptions (1 sheet) ---
        SheetSpec(
            sheet_id="subscriptions_saas_accounts",
            domain="subscriptions",
            description="Active software subscription accounts, seat counts and monthly fees.",
            columns=(
                ColumnSpec("Account ID", "text", _code_gen("SUB"), unique=True),
                ColumnSpec("Org Name", "text", _org_gen()),
                ColumnSpec(
                    "Plan Tier",
                    "category",
                    _cat_gen(("Starter", "Growth", "Business", "Enterprise")),
                    categories=("Starter", "Growth", "Business", "Enterprise"),
                ),
                ColumnSpec(
                    "Billing Cycle",
                    "category",
                    _cat_gen(("Monthly", "Annual")),
                    categories=("Monthly", "Annual"),
                ),
                ColumnSpec("Start Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec("Active Users", "integer", _int_gen(1, 350)),
                ColumnSpec("Monthly Fee", "decimal", _dec_gen(29.0, 2900.0), nullable=True),
            ),
        ),
        # --- 10. support_tickets (1 sheet) ---
        SheetSpec(
            sheet_id="support_helpdesk_queue",
            domain="support_tickets",
            description="Customer support tickets with severity, replies and resolution time.",
            columns=(
                ColumnSpec("Ticket ID", "text", _code_gen("TKT"), unique=True),
                ColumnSpec("Opened Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec(
                    "Queue",
                    "category",
                    _cat_gen(("Billing", "Technical", "Onboarding", "Account")),
                    categories=("Billing", "Technical", "Onboarding", "Account"),
                ),
                ColumnSpec(
                    "Severity",
                    "category",
                    _cat_gen(("Low", "Medium", "High", "Critical")),
                    categories=("Low", "Medium", "High", "Critical"),
                ),
                ColumnSpec("Agent Name", "text", _person_gen()),
                ColumnSpec("Replies Count", "integer", _int_gen(1, 18)),
                ColumnSpec("Resolution Hours", "decimal", _dec_gen(0.5, 96.0), nullable=True),
            ),
        ),
        # --- 11. marketing (1 sheet) ---
        SheetSpec(
            sheet_id="marketing_campaign_metrics",
            domain="marketing",
            description="Digital campaign performance with clicks, conversions and ad spend.",
            columns=(
                ColumnSpec("Campaign ID", "text", _code_gen("CMP"), unique=True),
                ColumnSpec("Launch Date", "date", _date_gen(d_2025_start, d_2026_mid)),
                ColumnSpec("Campaign Name", "text", _text_choice(_CAMPAIGNS)),
                ColumnSpec(
                    "Channel",
                    "category",
                    _cat_gen(("Search", "Social", "Email", "Affiliate", "Display")),
                    categories=("Search", "Social", "Email", "Affiliate", "Display"),
                ),
                ColumnSpec("Clicks", "integer", _int_gen(150, 25000)),
                ColumnSpec("Conversions", "integer", _int_gen(5, 1200)),
                ColumnSpec("Ad Spend", "decimal", _dec_gen(120.0, 15000.0), nullable=True),
            ),
        ),
    ]


def assign_splits(
    specs: list[SheetSpec],
    heldout_fraction: float = DEFAULT_HELDOUT_FRACTION,
    seed: int = 42,
) -> dict[str, Literal["train", "test"]]:
    """Deterministically hold out ~20% of sheets for the test set across distinct domains."""
    if not 0.0 < heldout_fraction < 1.0:
        raise ValueError("heldout_fraction must be between 0 and 1")

    rng = random.Random(seed)
    n_test = max(1, round(len(specs) * heldout_fraction))

    by_domain: dict[str, list[str]] = defaultdict(list)
    for spec in specs:
        by_domain[spec.domain].append(spec.sheet_id)

    domains = sorted(by_domain)
    rng.shuffle(domains)

    test_ids: set[str] = set()
    # Pick at most one sheet per domain first so held-out schemas span diverse domains.
    for domain in domains:
        if len(test_ids) >= n_test:
            break
        candidates = sorted(by_domain[domain])
        test_ids.add(rng.choice(candidates))

    if len(test_ids) < n_test:
        remaining = [s.sheet_id for s in specs if s.sheet_id not in test_ids]
        rng.shuffle(remaining)
        test_ids.update(remaining[: n_test - len(test_ids)])

    return {spec.sheet_id: ("test" if spec.sheet_id in test_ids else "train") for spec in specs}


def _generate_rows(
    spec: SheetSpec,
    num_rows: int,
    rng: random.Random,
    blank_rate: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row_idx in range(num_rows):
        row = {col.name: col.generator(rng, row_idx) for col in spec.columns}
        rows.append(row)

    # Inject a small controlled number of blank cells in designated nullable columns.
    nullable_cols = [col for col in spec.columns if col.nullable and not col.unique]
    if nullable_cols and blank_rate > 0:
        total_blanks = 0
        for col in nullable_cols:
            target = max(2, round(num_rows * blank_rate))
            target = min(target, max(1, num_rows // 5))
            blank_indices = rng.sample(range(num_rows), k=target)
            for idx in blank_indices:
                rows[idx][col.name] = None
            total_blanks += target
        assert total_blanks > 0
    return rows


def _write_csv(path: Path, columns: tuple[ColumnSpec, ...], rows: list[dict[str, Any]]) -> str:
    records = []
    for row in rows:
        formatted = {}
        for col in columns:
            val = row[col.name]
            if val is None:
                formatted[col.name] = ""
            elif isinstance(val, date):
                formatted[col.name] = val.isoformat()
            else:
                formatted[col.name] = val
        records.append(formatted)

    df = pd.DataFrame(records, columns=[c.name for c in columns])
    csv_text = df.to_csv(index=False, lineterminator="\n")
    path.write_text(csv_text, encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_xlsx(path: Path, columns: tuple[ColumnSpec, ...], rows: list[dict[str, Any]]) -> None:
    wb = openpyxl.Workbook()
    wb.properties.created = FIXED_XLSX_TIMESTAMP
    wb.properties.modified = FIXED_XLSX_TIMESTAMP
    ws = wb.active
    ws.title = "Sheet1"

    header_font = Font(bold=True)
    for col_idx, col in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col.name)
        cell.font = header_font

    for row_idx, row in enumerate(rows, start=2):
        for col_idx, col in enumerate(columns, start=1):
            val = row[col.name]
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            if isinstance(val, date):
                cell.number_format = "yyyy-mm-dd"
            elif col.col_type == "decimal" and val is not None:
                cell.number_format = "0.00"

    wb.save(path)


def _column_summary(col_idx: int, col: ColumnSpec, rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [r[col.name] for r in rows]
    non_null = [v for v in values if v is not None]
    null_count = len(values) - len(non_null)

    def _fmt(v: Any) -> Any:
        return v.isoformat() if isinstance(v, date) else v

    info: dict[str, Any] = {
        "letter": get_column_letter(col_idx),
        "name": col.name,
        "type": col.col_type,
        "nullable": col.nullable,
        "unique": col.unique,
        "null_count": null_count,
        "sample_values": [_fmt(v) for v in non_null[:3]],
    }
    if col.col_type == "category":
        info["categories"] = sorted({str(v) for v in non_null})
    elif col.col_type in ("integer", "decimal") and non_null:
        info["min"] = min(non_null)
        info["max"] = max(non_null)
    elif col.col_type == "date" and non_null:
        info["min"] = min(non_null).isoformat()
        info["max"] = max(non_null).isoformat()
    return info


def _relative_posix(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def generate_all_sheets(
    out_dir: str | Path,
    seed: int = 42,
    min_rows: int = DEFAULT_MIN_ROWS,
    max_rows: int = DEFAULT_MAX_ROWS,
    blank_rate: float = DEFAULT_BLANK_RATE,
    heldout_fraction: float = DEFAULT_HELDOUT_FRACTION,
) -> dict[str, Any]:
    """Generate all synthetic sheets as CSV + XLSX and write ``manifest.json``."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    specs = build_sheet_specs()
    splits = assign_splits(specs, heldout_fraction=heldout_fraction, seed=seed)
    rng = random.Random(seed)

    sheet_entries: list[dict[str, Any]] = []
    for spec in specs:
        num_rows = rng.randint(min_rows, max_rows)
        rows = _generate_rows(spec, num_rows=num_rows, rng=rng, blank_rate=blank_rate)

        csv_path = out_path / f"{spec.sheet_id}.csv"
        xlsx_path = out_path / f"{spec.sheet_id}.xlsx"
        csv_sha256 = _write_csv(csv_path, spec.columns, rows)
        _write_xlsx(xlsx_path, spec.columns, rows)

        col_meta = [
            _column_summary(idx, col, rows) for idx, col in enumerate(spec.columns, start=1)
        ]
        blank_cells = sum(c["null_count"] for c in col_meta)

        sheet_entries.append(
            {
                "sheet_id": spec.sheet_id,
                "domain": spec.domain,
                "split": splits[spec.sheet_id],
                "description": spec.description,
                "num_rows": num_rows,
                "num_cols": len(spec.columns),
                "blank_cells": blank_cells,
                "key_column": get_column_letter(spec.key_column_index + 1),
                "csv_path": _relative_posix(csv_path),
                "xlsx_path": _relative_posix(xlsx_path),
                "csv_sha256": csv_sha256,
                "columns": col_meta,
            }
        )

    train_ids = [s["sheet_id"] for s in sheet_entries if s["split"] == "train"]
    test_ids = [s["sheet_id"] for s in sheet_entries if s["split"] == "test"]
    manifest: dict[str, Any] = {
        "seed": seed,
        "num_sheets": len(sheet_entries),
        "train_sheets": len(train_ids),
        "test_sheets": len(test_ids),
        "heldout_fraction": round(len(test_ids) / len(sheet_entries), 4),
        "row_range": [min_rows, max_rows],
        "blank_rate": blank_rate,
        "domains": sorted({s["domain"] for s in sheet_entries}),
        "train_sheet_ids": train_ids,
        "test_sheet_ids": test_ids,
        "sheets": sheet_entries,
    }

    manifest_path = out_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="YAML merged over config/default.yaml")
    parser.add_argument("--seed", type=int, default=None, help="Override random seed")
    parser.add_argument("--out-dir", default=None, help="Override output directory")
    args = parser.parse_args()

    cfg = load_config(args.config)
    seed = cfg["seed"] if args.seed is None else args.seed
    out_dir = cfg["paths"]["sheets_dir"] if args.out_dir is None else Path(args.out_dir)
    min_rows, max_rows = cfg["data"]["rows_per_sheet"]
    blank_rate = cfg["data"].get("blank_rate", DEFAULT_BLANK_RATE)
    heldout_fraction = cfg["splits"]["heldout_schema_fraction"]

    log = get_logger("formulalm.sheets", log_file=cfg["paths"]["logs_dir"] / "sheets.log")
    log.info(
        "Generating synthetic sheets into %s (seed=%d, rows=%d..%d, heldout=%.2f)",
        out_dir,
        seed,
        min_rows,
        max_rows,
        heldout_fraction,
    )
    manifest = generate_all_sheets(
        out_dir=out_dir,
        seed=seed,
        min_rows=min_rows,
        max_rows=max_rows,
        blank_rate=blank_rate,
        heldout_fraction=heldout_fraction,
    )
    log.info(
        "Generated %d sheets (%d train, %d test) across %d domains; manifest saved to %s",
        manifest["num_sheets"],
        manifest["train_sheets"],
        manifest["test_sheets"],
        len(manifest["domains"]),
        Path(out_dir) / "manifest.json",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
