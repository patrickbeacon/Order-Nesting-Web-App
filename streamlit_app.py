
import io
import re
from datetime import datetime

import streamlit as st
import pathlib
import os
import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

st.set_page_config(
    page_title="Beacon Lite Order Nest",
    page_icon="assets/favicon.png",
    layout="centered",
)

# Inject your custom CSS
st.markdown(
    pathlib.Path("assets/branding.css").read_text(),
    unsafe_allow_html=True
)

st.title("Order Nest – PDF Generator")
st.caption("Upload Sales Order + Production Plan CSVs, apply your rules, and download a styled PDF.")

with st.expander("How it works"):
    st.markdown("""
    1. **Upload** today's *Sales* CSV and *Production Plan* CSV.
    2. Choose which column is your Sales Order Key, and which column is Order Print Status.
    3. Click **Generate PDF** to download a styled, grouped report.
    """)

sales_file = st.file_uploader("Sales CSV", type=["csv"], key="sales")
beacon_file = st.file_uploader("Production Plan CSV", type=["csv"], key="beacon")

def load_csv(uploaded):
    if uploaded is None:
        return None
    try:
        return pd.read_csv(uploaded)
    except Exception:
        uploaded.seek(0)
        return pd.read_csv(uploaded, encoding="latin-1")

sales_df = load_csv(sales_file)
beacon_df = load_csv(beacon_file)

if sales_df is not None:
    sales_df.columns = [str(c).strip() for c in sales_df.columns]
if beacon_df is not None:
    beacon_df.columns = [str(c).strip() for c in beacon_df.columns]

st.divider()

col1, col2 = st.columns(2)
with col1:
    st.subheader("Sales settings")
    if sales_df is not None:
        sales_cols = list(sales_df.columns)
        use_first = st.checkbox("Use first column as Sales Order key", value=True)
        if use_first:
            sales_key_col = sales_cols[0]
        else:
            sales_key_col = st.selectbox("Sales Order key column", options=sales_cols, index=min(0, len(sales_cols)-1))
    else:
        st.info("Upload a Sales CSV to pick the key column.")
        sales_key_col = None

with col2:
    st.subheader("Production Plan settings")
    graphics_selector = None
    if beacon_df is not None:
        beacon_cols = list(beacon_df.columns)
        mode = st.radio("Graphics Completed Date column", ["10th column (index 9)", "Pick by name"], horizontal=True)
        if mode == "10th column (index 9)":
            graphics_selector = 9
            st.caption(f"Using column: **{beacon_cols[9] if len(beacon_cols) > 9 else '(index 9 not present)'}**")
        else:
            graphics_by_name = st.selectbox("Pick column by name", options=beacon_cols, index=min(9, len(beacon_cols)-1))
            graphics_selector = graphics_by_name
    else:
        st.info("Upload a Production Plan CSV to choose the graphics-completed column.")

st.divider()

def is_blank(val):
    if pd.isna(val):
        return True
    return str(val).strip() == ""

def extract_text_fields(row):
    parts = []
    for col in ["Item", "Info", "Client", "Customer Name"]:
        if col in row and pd.notna(row[col]):
            parts.append(str(row[col]))
    return " || ".join(parts).upper()

GRADE_PATTERNS = [
    ("High Intensity Grade Reflective", r"HIGH\s*INTENSITY"),
    ("DIAMOND GRADE REFLECTIVE", r"DIAMOND\s*GRADE"),
    ("Engineer Grade Reflective", r"ENGINEER\s*GRADE"),
    ("Generic Vinyl", r"GENERIC\s*(PRINT)?\s*VINYL|^GENERIC$| GENERIC[^\w]?"),
    ("Flat Wrap", r"FLAT\s*WRAP"),
]

def find_group(row):
    text = extract_text_fields(row)
    if "ROLL UP" in text:
        return "__ROLL_UP__"
    if "LEXAN" in text:
        return "__LEXAN__"
    if "GUIDEWAYS" in text:
        return "__KIEWIT_GUIDEWAY__"
    for label, pat in GRADE_PATTERNS:
        if re.search(pat, text, flags=re.I):
            return label
    return "__MISC__"

def fmt_date(d):
    if pd.isna(d) or str(d).strip()=="" or str(d).strip().lower()=="nan":
        return ""
    dt = pd.to_datetime(d, errors="coerce")
    if pd.isna(dt):
        return ""
    return dt.strftime("%m/%d/%y")

def clean_val(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v)
    return "" if s.lower()=="nan" else s

def build_pdf(display_df: pd.DataFrame, present_headers):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        rightMargin=0.5*inch, leftMargin=0.5*inch,
        topMargin=0.6*inch, bottomMargin=0.6*inch,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleBig", fontSize=36, leading=42, alignment=1, spaceAfter=12))
    styles.add(ParagraphStyle(name="Subtle", fontSize=12, leading=14, alignment=1, textColor=colors.HexColor("#555555"), spaceAfter=6))
    styles.add(ParagraphStyle(name="Cell", fontSize=7, leading=9))
    styles.add(ParagraphStyle(name="Header", fontSize=9, leading=11, textColor=colors.white))

    elements = []
    elements.append(Spacer(1, 2*inch))
    elements.append(Paragraph("Order Nest", styles["TitleBig"]))
    elements.append(Paragraph(datetime.now().strftime("%B %d, %Y"), styles["Subtle"]))
    elements.append(PageBreak())

    vibrant = ["#2563EB","#059669","#DC2626","#7C3AED","#EA580C","#0EA5E9","#D946EF","#16A34A"]
    def header_color(i): return colors.HexColor(vibrant[i % len(vibrant)])

    default_widths = {
        "Sales Order": 0.9*inch,
        "Quote Number": 0.9*inch,
        "Client": 1.2*inch,
        "Item": 1.9*inch,
        "Info": 1.9*inch,
        "Quantity": 0.7*inch,
        "Due Date": 0.7*inch,
    }
    col_widths = [default_widths.get(h, 0.9*inch) for h in present_headers]
    total_w = sum(col_widths)

    def sort_key(row):
        d = row.get("Due Date", "")
        try:
            return datetime.strptime(d, "%m/%d/%y")
        except Exception:
            return datetime.max

    group_min = {}
    for g, df in display_df.groupby("Group"):
        if df.empty:
            group_min[g] = datetime.max
        else:
            group_min[g] = min([sort_key(r) for r in df.to_dict("records")] or [datetime.max])
    ordered_groups = sorted(group_min.keys(), key=lambda g: group_min[g])
    if "__MISC__" in ordered_groups:
        ordered_groups = [g for g in ordered_groups if g != "__MISC__"] + ["__MISC__"]

    group_labels = {"__ROLL_UP__":"Roll Up","__LEXAN__":"Lexan","__MISC__":"Miscellaneous"}

    def make_table(title, df, color_index):
        df = df.copy()
        df["__sort__"] = [sort_key(r) for r in df.to_dict("records")]
        df = df.sort_values("__sort__").drop(columns="__sort__")

        header_cells = [Paragraph(f"<b>{h}</b>", styles["Header"]) for h in present_headers]
        data = [header_cells]
        for _, r in df.iterrows():
            data.append([Paragraph(clean_val(r.get(h, "")), styles["Cell"]) for h in present_headers])

        tbl = Table(data, colWidths=col_widths, hAlign="CENTER")
        ts = TableStyle([
            ("FONT", (0,0), (-1,0), "Helvetica-Bold", 9),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("BACKGROUND", (0,0), (-1,0), header_color(color_index)),
            ("ALIGN", (0,0), (-1,-1), "LEFT"),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("INNERGRID", (0,0), (-1,-1), 0.25, colors.HexColor("#9CA3AF")),
            ("BOX", (0,0), (-1,-1), 0.6, colors.HexColor("#6B7280")),
            ("LEFTPADDING", (0,0), (-1,-1), 5),
            ("RIGHTPADDING", (0,0), (-1,-1), 5),
            ("TOPPADDING", (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ])
        for i in range(1, len(data)):
            ts.add("BACKGROUND", (0, i), (-1, i), colors.whitesmoke if i % 2 == 0 else colors.white)
        tbl.setStyle(ts)

        title_par = Paragraph(f"<para align='left'><b>{title}</b></para>",
                              ParagraphStyle(name="GroupTitle", fontSize=12, leading=14, textColor=colors.white, alignment=TA_LEFT))
        title_bar = Table([[title_par]], colWidths=[total_w], hAlign="CENTER")
        title_bar.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), header_color(color_index)),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6),
            ("TOPPADDING", (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("BOX", (0,0), (-1,-1), 0.6, header_color(color_index)),
        ]))
        return [title_bar, Spacer(1, 0.1*inch), tbl]

    elements = elements  # keep linter happy
    color_idx = 0
    for g in ordered_groups:
        df = display_df[display_df["Group"] == g]
        if df.empty:
            continue
        title = group_labels.get(g, g)
        tbl_parts = make_table(title, df, color_idx)
        for part in tbl_parts:
            elements.append(part)
        elements.append(PageBreak())
        color_idx += 1

    if len(elements) <= 4:
        elements.append(Paragraph("No matching rows to display", styles["Subtle"]))

    doc.build(elements)
    buf.seek(0)
    return buf

run_clicked = st.button("Generate PDF", type="primary", disabled=(sales_df is None or beacon_df is None or sales_key_col is None or graphics_selector is None))

if run_clicked:
    # Build normalized keys
    sales = sales_df.copy()
    beacon = beacon_df.copy()

    beacon_first = beacon.columns[0]
    # Graphics column via index or name
    if isinstance(graphics_selector, int):
        if graphics_selector >= len(beacon.columns):
            st.error(f"Graphics column index {graphics_selector} out of range.")
            st.stop()
        graphics_col = beacon.columns[graphics_selector]
    else:
        graphics_col = graphics_selector

    # Keep beacon rows where first col is non-empty
    beacon = beacon[beacon[beacon_first].apply(lambda x: pd.notna(x) and str(x).strip() != "")].copy()

    sales["__SO_KEY__"] = sales[sales_key_col].astype(str).str.strip().str.upper()
    beacon["__SO_KEY__"] = beacon[beacon_first].astype(str).str.strip().str.upper()

    merged = sales.merge(beacon[["__SO_KEY__", graphics_col]], on="__SO_KEY__", how="inner")

    # Filter out completed
    keep = merged[graphics_col].apply(lambda v: pd.isna(v) or str(v).strip() == "")
    filtered = merged[keep].copy()

    # Grouping
    filtered["Group"] = filtered.apply(find_group, axis=1)

    # Prepare display columns
    preferred_headers = ["Sales Order","Quote Number","Client","Item","Info","Quantity","Due Date"]
    filtered = filtered.rename(columns={sales_key_col: "Sales Order"})
    present_headers = [h for h in preferred_headers if h in filtered.columns]

    for col in present_headers:
        if col == "Due Date":
            filtered[col] = filtered[col].apply(fmt_date)
        else:
            filtered[col] = filtered[col].apply(lambda x: "" if str(x).lower()=="nan" else ("" if pd.isna(x) else str(x)))

    # Build and provide download
    pdf_buf = build_pdf(filtered, present_headers)
    st.success("Done! Download your PDF below.")
    st.download_button("Download Order Nest PDF", data=pdf_buf, file_name="Order_Nest_Today.pdf", mime="application/pdf")
