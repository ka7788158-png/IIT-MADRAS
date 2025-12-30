import streamlit as st
import json
import re
from pypdf import PdfReader
import math
import datetime
import os
import pandas as pd 
import plotly.express as px
import numpy as np
import time

# --- Set page title and wide layout ---
st.set_page_config(
    page_title="InfraCalc - Road Safety Estimator",
    layout="wide",
)

# ---(Loading Databases) ---
@st.cache_data # Cache the data for better performance
def load_data():
    try:
        with open('database.json', 'r', encoding='utf-8') as f:
            spec_db = json.load(f)
        with open('prices.json', 'r', encoding='utf-8') as f:
            price_db = json.load(f)
        return spec_db, price_db
    except FileNotFoundError as e:
        st.error(f"ERROR: Database file not found. Make sure 'database.json' and 'prices.json' are in the same folder. Details: {e}")
        return None, None
    except json.JSONDecodeError as e:
        st.error(f"ERROR: Could not read database file. Check JSON formatting. Details: {e}")
        return None, None

# --- Helper Functions for GIS Map (Unchanged) ---
def parse_chainage(ch_str):
    try:
        parts = ch_str.split('+'); return int(parts[0]) * 1000 + int(parts[1]) if len(parts) == 2 else int(parts[0])
    except: return None
def interpolate_gps(chainage_m, start_ch, end_ch, start_gps, end_gps):
    try:
        fraction = (chainage_m - start_ch) / (end_ch - start_ch)
        if fraction < 0: fraction = 0; 
        if fraction > 1: fraction = 1
        lat = start_gps[0] + (end_gps[0] - start_gps[0]) * fraction
        lon = start_gps[1] + (end_gps[1] - start_gps[1]) * fraction
        return lat, lon
    except: return start_gps

# --- Load Data ---
spec_database, price_database = load_data()

# --- Main App ---
st.title("🚧 Road Safety Intervention Cost Estimator")
st.markdown("This dashboard estimates material costs from a PDF report or manual entry, based on IRC standards.")

if not spec_database or not price_database:
    st.error("Error: Database files (`database.json` or `prices.json`) could not be loaded. The app cannot run.")
else:
    # --- Create the Main App Tabs ---
    tab_pdf, tab_manual, tab_how_to = st.tabs(["📈 PDF Report Estimator", "✍️ Manual Entry Estimator", "ℹ️ How to Use"])

    # ==============================================================================
    # --- TAB 1: PDF REPORT ESTIMATOR ---
    # ==============================================================================
    with tab_pdf:
        col1, col2 = st.columns([1, 2]) # 1/3 width for controls, 2/3 for results

        # --- Column1 : Controls ---
        with col1:
            st.markdown("## 📊 InfraCalc")
            st.subheader("Controls")
            uploaded_file = st.file_uploader("Upload PDF Report", type="pdf")

            # Editable Prices
            editable_prices = {} 
            with st.expander("Override Material Prices (Optional)"):
                for item_name, default_price in price_database.items():
                    editable_prices[item_name] = st.number_input(
                        label=item_name, value=float(default_price), min_value=0.0,
                        step=10.0, format="%.2f", key=f"pdf_price_{item_name}"
                    )
            
            # Feature: Explainability Viewer
            with st.expander("View Specification Logic (Explainability)"):
                st.write("This table shows the material breakdown for each intervention, based on IRC standards research.")
                explain_data = []
                for key, value in spec_database.items():
                    materials = []
                    if "materials_per_item" in value: materials = [f"{m.get('quantity', 0)} {m.get('unit', '')} of {m.get('name', '')}" for m in value.get("materials_per_item", [])]
                    elif "materials_per_meter" in value: materials = [f"{m.get('quantity', 0)} {m.get('unit', '')}/meter of {m.get('name', '')}" for m in value.get("materials_per_meter", [])]
                    elif "materials_per_cubic_meter" in value: materials = [f"{m.get('quantity', 0)} {m.get('unit', '')}/m³ of {m.get('name', '')}" for m in value.get("materials_per_cubic_meter", [])]
                    elif "materials_per_sqm_20mm" in value: materials = [f"{m.get('quantity', 0)} {m.get('unit', '')}/sqm of {m.get('name', '')}" for m in value.get("materials_per_sqm_20mm", [])]
                    explain_data.append({"Intervention Keyword": key, "Source Clause": value.get("source_clause", "N/A"), "Material Breakdown": ", ".join(materials)})
                st.dataframe(pd.DataFrame(explain_data))
            
            # Feature: Map Assumptions
            with st.expander("GIS Map Assumptions"):
                st.info("Map plots interventions assuming the report's chainage (e.g., 4+200) maps proportionally to the GPS line from Problem 2.")
                st.json({"Start_GPS": [10.310709, 77.944926], "End_GPS": [10.306490, 77.943170], "Assumed_Start_Chainage": "4+100", "Assumed_End_Chainage": "362+500"})
            
            st.info("💡 **Tip:** Change theme in Settings (☰) > Settings.")

        # --- Column 2: Results ---
        with col2:
            st.subheader("Results")
            if uploaded_file is not None:
                # Add Spinner
                with st.spinner("Processing Report... This may take a moment."):
                    time.sleep(1) # Small delay to make spinner visible
                    
                    # Process the PDF
                    try:
                        reader = PdfReader(uploaded_file)
                        full_report_text = ""
                        for page in reader.pages:
                            page_text = page.extract_text(); 
                            if page_text: full_report_text += page_text
                        full_report_text_lower = full_report_text.lower()
                    except Exception as e:
                        st.error(f"Error reading PDF file: {e}"); full_report_text = None

                    # Perform Calculation & Build Report
                    if full_report_text:
                        total_project_cost = 0; report_lines = []; results_list = []; map_data = []
                        
                        START_GPS = (10.310709, 77.944926); END_GPS = (10.306490, 77.943170)
                        START_CH = parse_chainage("4+100"); END_CH = parse_chainage("362+500")
                        
                        report_lines.append(f"Input Report File: {uploaded_file.name}\n")
                        report_lines.append("ITEMIZED COST BREAKDOWN\n" + "-"*40 + "\n")

                        # Loop through interventions
                        for intervention_key, specs_original in spec_database.items():
                            specs = specs_original.copy() 
                            if intervention_key.lower() in full_report_text_lower:
                                report_lines.append(f"Intervention: {intervention_key.upper()}")
                                quantity_found = 0; unit_type = "item";
                                
                                # (Quantity Logic)
                                if "materials_per_meter" in specs:
                                    unit_type = "meter"; quantity_found = 1 
                                    if intervention_key.lower() == "longitudinal markings": match = re.search(r'(\d+)\s*m', full_report_text_lower, re.IGNORECASE); quantity_found = float(match.group(1)) if match else 1
                                    elif intervention_key.lower() == "streetlights": quantity_found = 1000.0 
                                    elif intervention_key.lower() == "road studs":
                                        unit_type = "item" 
                                        chainage_match = re.search(r'(\d+)\+(\d+)\s+to\s+(\d+)\+(\d+)', full_report_text_lower, re.IGNORECASE)
                                        if chainage_match:
                                            start_km, start_m, end_km, end_m = map(int, chainage_match.groups())
                                            length_m = abs(((end_km * 1000) + end_m) - ((start_km * 1000) + start_m))
                                            studs_per_edge = math.ceil(length_m / 9.0); quantity_found = studs_per_edge * 2 
                                        else: quantity_found = 1 
                                elif "materials_per_item" in specs:
                                    unit_type = "item"; quantity_found = full_report_text_lower.count(intervention_key.lower()); quantity_found = 1 if quantity_found == 0 else quantity_found
                                elif "materials_per_cubic_meter" in specs:
                                    unit_type = "m^3"; quantity_found = 0 
                                    area_match = re.search(r'area\s*([\d\.]+)\s*sqm', full_report_text_lower, re.IGNORECASE)
                                    depth_match = re.search(r'([\d\.]+)\s*mm\s*depth', full_report_text_lower, re.IGNORECASE)
                                    if area_match and depth_match and intervention_key.lower() == "pothole":
                                        area_sqm = float(area_match.group(1)); depth_mm = float(depth_match.group(1)); depth_m = depth_mm / 1000; quantity_found = area_sqm * depth_m
                                elif "materials_per_sqm_20mm" in specs:
                                    unit_type = "sqm"; quantity_found = 1 
                                    area_match = re.search(r'area\s*([\d\.]+)\s*sqm', full_report_text_lower, re.IGNORECASE)
                                    if area_match and intervention_key.lower() == "pothole": quantity_found = float(area_match.group(1))
                                
                                report_lines.append(f"  Quantity Found: {quantity_found:.2f} {unit_type}(s)")
                                report_lines.append(f"  Source Clause: {specs['source_clause']}")
                                report_lines.append("  Cost Breakdown:")

                                # Find Chainage for Map
                                found_ch_str = None
                                try:
                                    for match in re.finditer(intervention_key.lower(), full_report_text_lower):
                                        search_window = full_report_text[max(0, match.start() - 150):match.start()]
                                        ch_match = re.search(r'(\d+\+\d+)', search_window)
                                        if ch_match: found_ch_str = ch_match.group(1); break
                                except Exception: pass 
                                
                                # (Calculate Cost)
                                item_total_cost = 0
                                materials_list = []
                                if "materials_per_item" in specs: materials_list = specs.get("materials_per_item", [])
                                elif "materials_per_meter" in specs: materials_list = specs.get("materials_per_meter", [])
                                elif "materials_per_cubic_meter" in specs: materials_list = specs.get("materials_per_cubic_meter", [])
                                elif "materials_per_sqm_20mm" in specs: materials_list = specs.get("materials_per_sqm_20mm", [])

                                for material in materials_list:
                                    mat_name = material["name"]
                                    mat_qty_per_unit = material["quantity"]
                                    
                                    if intervention_key.lower() == "road studs" and unit_type == "item":
                                        mat_qty_needed = quantity_found * mat_qty_per_unit
                                    else:
                                        mat_qty_needed = mat_qty_per_unit * quantity_found
                                    
                                    if mat_name in editable_prices:
                                        mat_price_per_unit = editable_prices[mat_name]
                                        line_cost = mat_qty_needed * mat_price_per_unit
                                        item_total_cost += line_cost
                                        report_lines.append(f"    - {mat_name}: {mat_qty_needed:.2f} units @ ₹{mat_price_per_unit:.2f}/unit = ₹{line_cost:.2f}")
                                    else:
                                        report_lines.append(f"    - {mat_name}: {mat_qty_needed:.2f} units @ PRICE NOT FOUND")
                                
                                report_lines.append(f"  TOTAL for {intervention_key}: ₹{item_total_cost:.2f}\n")
                                total_project_cost += item_total_cost
                                if item_total_cost > 0:
                                    results_list.append({"Intervention": intervention_key, "Quantity": f"{quantity_found:.2f}", "Unit": unit_type, "Source Clause": specs['source_clause'], "Material Cost (₹)": item_total_cost})
                                    if found_ch_str:
                                        chainage_m = parse_chainage(found_ch_str)
                                        if chainage_m:
                                            lat, lon = interpolate_gps(chainage_m, START_CH, END_CH, START_GPS, END_GPS)
                                            map_data.append({"name": f"{intervention_key} (at {found_ch_str})", "lat": lat, "lon": lon})

                        # (Add Final Summary to report_lines)
                        report_lines.append("SUMMARY\n" + "-"*40 + "\n")
                        report_lines.append(f"TOTAL ESTIMATED MATERIAL COST: ₹{total_project_cost:.2f}\n")

                        # --- Display the results in Column 2 ---
                        
                        # (KPI Dashboard)
                        st.subheader("High-Level Summary")
                        kpi1, kpi2, kpi3 = st.columns(3)
                        kpi1.metric(label="Total Estimated Material Cost", value=f"₹ {total_project_cost:,.2f}")
                        kpi2.metric(label="Total Interventions Found", value=len(results_list))
                        if results_list: most_expensive = max(results_list, key=lambda item: item['Material Cost (₹)']); kpi3.metric(label="Most Expensive Item", value=most_expensive['Intervention'], help=f"Cost: ₹{most_expensive['Material Cost (₹)']:,.2f}")
                        else: kpi3.metric(label="Most Expensive Item", value="N/A")
                        st.markdown("---")

                        # (GIS Map)
                        if map_data:
                            st.subheader("Intervention Location Map")
                            map_df = pd.DataFrame(map_data); st.map(map_df, zoom=15)
                        
                        # (Interactive Plotly Charts)
                        if results_list:
                            st.subheader("Cost Analysis Charts")
                            chart_df = pd.DataFrame(results_list)
                            fig_bar = px.bar(chart_df, x='Intervention', y='Material Cost (₹)', title="Cost Breakdown by Intervention", hover_data=['Quantity', 'Unit', 'Source Clause'])
                            st.plotly_chart(fig_bar, use_container_width=True)
                            fig_pie = px.pie(chart_df, names='Intervention', values='Material Cost (₹)', title="Cost Contribution (%)")
                            st.plotly_chart(fig_pie, use_container_width=True)

                        # (Interactive Dataframe)
                        if results_list:
                            st.subheader("Interactive Summary Table")
                            results_df = pd.DataFrame(results_list)
                            results_df['Material Cost (₹)'] = results_df['Material Cost (₹)'].apply(lambda x: f"₹{x:,.2f}")
                            st.dataframe(results_df, use_container_width=True)
                        
                        # --- NEW: CSV Download Button ---
                        if results_list:
                            # Create a clean DataFrame for CSV export (with raw numbers)
                            csv_df = pd.DataFrame(results_list)
                            csv_data = csv_df.to_csv(index=False).encode('utf-8')
                            
                            st.download_button(
                                label="Download Summary Table (.csv)",
                                data=csv_data,
                                file_name=f"cost_summary_{uploaded_file.name}.csv",
                                mime='text/csv',
                                key='pdf_csv_download'
                            )

                        # (Download Button & Text Expander)
                        st.download_button(label="Download Full Report (.txt)", data='\n'.join(report_lines), file_name=f"cost_report_{uploaded_file.name}.txt", mime='text/plain', key='pdf_txt_download')
                        with st.expander("Click to see detailed text report"):
                            st.code('\n'.join(report_lines), language='text')

                        # (Success Animation)
                        st.balloons()
            
            else: 
                st.info("Please upload a PDF file in the control panel on the left to begin.")

    # ==============================================================================
    # --- TAB 2: MANUAL ENTRY ESTIMATOR ---
    # ==============================================================================
    with tab_manual:
        
        if 'manual_items' not in st.session_state: st.session_state.manual_items = []
        
        col1_manual, col2_manual = st.columns([1, 2])

        # --- Column 1: Manual Controls ---
        with col1_manual:
            st.markdown("## 📊 InfraCalc")
            
            st.subheader("Manual Intervention Entry")
            with st.form("manual_entry_form", clear_on_submit=True):
                item_options = list(spec_database.keys())
                selected_item = st.selectbox("Select Intervention", item_options)
                
                default_unit = "item"
                if "materials_per_meter" in spec_database[selected_item]: default_unit = "meter(s)"
                elif "materials_per_cubic_meter" in spec_database[selected_item]: default_unit = "m^3"
                elif "materials_per_sqm_20mm" in spec_database[selected_item]: default_unit = "sqm (at 20mm depth)"
                
                quantity = st.number_input(f"Quantity ({default_unit})", min_value=0.01, step=1.0)
                
                submitted = st.form_submit_button("Add Item to List")
                if submitted:
                    st.session_state.manual_items.append({"key": selected_item, "quantity": quantity, "unit": default_unit.split('(')[0].strip()})
                    st.success(f"Added {quantity} {default_unit.split('(')[0].strip()} of {selected_item}")
            
            # (Price editor for manual tab)
            manual_editable_prices = {}
            with st.expander("Override Material Prices (Optional)"):
                for item_name, default_price in price_database.items():
                    manual_editable_prices[item_name] = st.number_input(
                        label=item_name, value=float(default_price), min_value=0.0,
                        step=10.0, format="%.2f", key=f"manual_price_{item_name}"
                    )

        # --- Column 2: Manual Results ---
        with col2_manual:
            st.subheader("Current Intervention List & Results")
            
            if not st.session_state.manual_items:
                st.info("No items added yet. Use the form on the left to add interventions.")
            else:
                st.dataframe(pd.DataFrame(st.session_state.manual_items), use_container_width=True)
                if st.button("Clear List"):
                    st.session_state.manual_items = []
                    st.rerun() 
                
                if st.button("Calculate Manual Cost"):
                    # (Add Spinner)
                    with st.spinner("Calculating..."):
                        time.sleep(0.5) # Small delay
                        total_project_cost = 0; report_lines = []; results_list = []

                        report_lines.append(f"Manual Report Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        report_lines.append("ITEMIZED COST BREAKDOWN\n" + "-"*40 + "\n")

                        for item in st.session_state.manual_items:
                            intervention_key = item["key"]; quantity_found = item["quantity"]; unit_type = item["unit"]
                            specs = spec_database[intervention_key]
                            
                            report_lines.append(f"Intervention: {intervention_key.upper()}")
                            report_lines.append(f"  Quantity Found: {quantity_found:.2f} {unit_type}(s)")
                            report_lines.append(f"  Source Clause: {specs['source_clause']}")
                            report_lines.append("  Cost Breakdown:")

                            item_total_cost = 0
                            materials_list = []
                            if "materials_per_item" in specs: materials_list = specs.get("materials_per_item", [])
                            elif "materials_per_meter" in specs: materials_list = specs.get("materials_per_meter", [])
                            elif "materials_per_cubic_meter" in specs: materials_list = specs.get("materials_per_cubic_meter", [])
                            elif "materials_per_sqm_20mm" in specs: materials_list = specs.get("materials_per_sqm_20mm", [])

                            for material in materials_list:
                                mat_name = material["name"]
                                mat_qty_per_unit = material["quantity"]
                                mat_qty_needed = mat_qty_per_unit * quantity_found
                                
                                if mat_name in manual_editable_prices:
                                    mat_price_per_unit = manual_editable_prices[mat_name]
                                    line_cost = mat_qty_needed * mat_price_per_unit
                                    item_total_cost += line_cost
                                    report_lines.append(f"    - {mat_name}: {mat_qty_needed:.2f} units @ ₹{mat_price_per_unit:.2f}/unit = ₹{line_cost:.2f}")
                                else:
                                    report_lines.append(f"    - {mat_name}: {mat_qty_needed:.2f} units @ PRICE NOT FOUND")
                            
                            report_lines.append(f"  TOTAL for {intervention_key}: ₹{item_total_cost:.2f}\n")
                            total_project_cost += item_total_cost
                            if item_total_cost > 0:
                                results_list.append({"Intervention": intervention_key, "Quantity": f"{quantity_found:.2f}", "Unit": unit_type, "Source Clause": specs['source_clause'], "Material Cost (₹)": item_total_cost})
                        
                        report_lines.append("SUMMARY\n" + "-"*40 + "\n")
                        report_lines.append(f"TOTAL ESTIMATED MATERIAL COST: ₹{total_project_cost:.2f}\n")

                        # (Display the results)
                        kpi1_man, kpi2_man, kpi3_man = st.columns(3)
                        kpi1_man.metric(label="Total Estimated Material Cost", value=f"₹ {total_project_cost:,.2f}")
                        kpi2_man.metric(label="Total Interventions Found", value=len(results_list))
                        if results_list: most_expensive = max(results_list, key=lambda item: item['Material Cost (₹)']); kpi3_man.metric(label="Most Expensive Item", value=most_expensive['Intervention'], help=f"Cost: ₹{most_expensive['Material Cost (₹)']:,.2f}")
                        else: kpi3_man.metric(label="Most Expensive Item", value="N/A")
                        st.markdown("---")

                        if results_list:
                            st.subheader("Interactive Summary Table")
                            results_df_man = pd.DataFrame(results_list)
                            results_df_man['Material Cost (₹)'] = results_df_man['Material Cost (₹)'].apply(lambda x: f"₹{x:,.2f}")
                            st.dataframe(results_df_man, use_container_width=True)
                            
                            st.subheader("Cost Analysis Charts")
                            chart_df_man = pd.DataFrame(results_list)
                            fig_bar_man = px.bar(chart_df_man, x='Intervention', y='Material Cost (₹)', title="Cost Breakdown by Intervention")
                            st.plotly_chart(fig_bar_man, use_container_width=True)
                            fig_pie_man = px.pie(chart_df_man, names='Intervention', values='Material Cost (₹)', title="Cost Contribution (%)")
                            st.plotly_chart(fig_pie_man, use_container_width=True)
                        
                        # --- NEW: CSV Download Button ---
                        if results_list:
                            csv_df_man = pd.DataFrame(results_list)
                            csv_data_man = csv_df_man.to_csv(index=False).encode('utf-8')
                            
                            st.download_button(
                                label="Download Summary Table (.csv)",
                                data=csv_data_man,
                                file_name="manual_cost_summary.csv",
                                mime='text/csv',
                                key='manual_csv_download'
                            )

                        st.download_button(label="Download Full Report (.txt)", data='\n'.join(report_lines), file_name="manual_cost_report.txt", mime='text/plain', key='manual_txt_download')
                        with st.expander("Click to see detailed text report"):
                            st.code('\n'.join(report_lines), language='text')

                    # (Success Animation)
                    st.balloons()

    # ==============================================================================
    # --- TAB 3: HOW TO USE ---
    # ==============================================================================
    with tab_how_to:
        st.subheader("Welcome to the InfraCalc Estimator!")
        st.markdown("""
        This tool is designed to help you quickly estimate the *material-only costs* for road safety interventions. 
        You can use it in two ways:
        """)
        st.info("ℹ️ **Note:** This tool only estimates **material costs**. It does not include labor, installation, or taxes.")
        st.markdown("---")
        st.subheader("Method 1: Using the 📈 PDF Report Estimator")
        st.markdown("""
        This is the primary, AI-powered feature. It reads an official intervention report and calculates the costs automatically.
        **How to use it:**
        1.  **Go to the "📈 PDF Report Estimator" tab.**
        2.  In the **Controls** panel on the left, click **"Upload PDF Report"** and select your file (like the `Road_Safety_InterVention_Report_Final.pdf`).
        3.  Wait for the spinner to finish processing.
        4.  **View your results** in the **Results** panel on the right!
        **Results include:**
        * **High-Level Summary:** The total cost, number of interventions, and the most expensive item.
        * **GIS Map:** A map showing the estimated location of each intervention based on its chainage.
        * **Interactive Charts:** Bar and pie charts showing the cost breakdown.
        * **Interactive Table:** A sortable table of all interventions and their costs.
        * **Downloadable Report:** A `.txt` file with the full, detailed breakdown and a **`.csv` file** for use in Excel.
        """)
        st.markdown("#### Advanced PDF Features:")
        st.markdown("""
        * **Override Material Prices:** In the "Controls" panel, you can open this expander to change the default price for any material (e.g., if you have a new quote for "Thermoplastic Paint").
        * **View Specification Logic:** Open this expander to see the database that powers the app. It shows exactly how the app knows what materials are needed for each intervention, fulfilling the **Explainability** requirement.
        """)
        st.markdown("---")
        st.subheader("Method 2: Using the ✍️ Manual Entry Estimator")
        st.markdown("""
        Use this tab if you don't have a PDF report and just want a quick quote for a few items.
        **How to use it:**
        1.  **Go to the "✍️ Manual Entry Estimator" tab.**
        2.  In the **Controls** panel on the left, use the form:
            * Select an intervention (e.g., "Pothole").
            * Enter the quantity (e.g., "5" for 5 sqm).
            * Click **"Add Item to List"**.
        3.  Repeat for all the items you want to cost.
        4.  When your list is complete, click the **"Calculate Manual Cost"** button in the **Results** panel.
        5.  Your results (KPIs, charts, tables, and downloads) will appear just like in the PDF tab.
        """)