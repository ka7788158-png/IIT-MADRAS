import json
import re
from pypdf import PdfReader
import math
import datetime # Import datetime to add timestamp to report

# --- MODULE 2: LOAD OUR DATABASES ("Brain" and "Prices") ---
print("Loading databases...")
try:
    with open('database.json', 'r', encoding='utf-8') as f: # Added encoding='utf-8'
        spec_database = json.load(f)
    print("Specification database loaded.")
    
    with open('prices.json', 'r', encoding='utf-8') as f: # Added encoding='utf-8'
        price_database = json.load(f)
    print("Price database loaded.")
except FileNotFoundError as e:
    print(f"ERROR: Could not find database file. {e}")
    exit()

# --- MODULE 1: READ THE PDF REPORT ("Reader") ---
print("\nReading intervention report...")
report_path = 'Road_Safety_Intervention_Report_Final.pdf' 
try:
    reader = PdfReader(report_path)
except FileNotFoundError:
    print(f"ERROR: Input PDF file not found at '{report_path}'")
    exit()

full_report_text = ""
for page in reader.pages:
    page_text = page.extract_text()
    if page_text:
        full_report_text += page_text
        
full_report_text = full_report_text.lower()
print("PDF report text extracted and converted to lowercase.")

# --- MODULE 4: FIND JOBS & CALCULATE ("Calculator") ---
print("\n--- STARTING ESTIMATION ---")
report_filename = "cost_report.txt"
# --- FIX: Open the output file with UTF-8 encoding ---
with open(report_filename, 'w', encoding='utf-8') as report_file:
    
    # Write Report Header
    report_file.write("=========================================\n")
    report_file.write("   NATIONAL ROAD SAFETY HACKATHON 2025\n")
    report_file.write("        Material Cost Estimation Report\n")
    report_file.write("=========================================\n\n")
    report_file.write(f"Report Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    report_file.write(f"Input Report File: {report_path}\n\n")
    report_file.write("-----------------------------------------\n")
    report_file.write("        ITEMIZED COST BREAKDOWN\n")
    report_file.write("-----------------------------------------\n\n")

    final_estimates = []
    total_project_cost = 0

    # Loop through every intervention we know about (from database.json)
    for intervention_key, specs in spec_database.items():
        
        # Check if the lowercase keyword is in the lowercase PDF text
        if intervention_key.lower() in full_report_text:
            print(f"\nFound intervention: '{intervention_key}'")
            report_file.write(f"Intervention: {intervention_key.upper()}\n")
            
            quantity_found = 0
            unit_type = ""
            
            # --- Quantity Logic ---
            if "materials_per_meter" in specs:
                unit_type = "meter"
                quantity_found = 1 
                if intervention_key.lower() == "longitudinal markings":
                    match = re.search(r'(\d+)\s*m', full_report_text, re.IGNORECASE)
                    if match: quantity_found = float(match.group(1))
                elif intervention_key.lower() == "streetlights":
                     print("  > Assuming 'entire stretch' for streetlights is 1000m.")
                     quantity_found = 1000.0 
            elif "materials_per_item" in specs:
                unit_type = "item"
                quantity_found = full_report_text.count(intervention_key.lower())
                if quantity_found == 0: quantity_found = 1 
            elif "materials_per_cubic_meter" in specs:
                unit_type = "m^3"
                quantity_found = 0 
                area_match = re.search(r'area\s*([\d\.]+)\s*sqm', full_report_text, re.IGNORECASE)
                depth_match = re.search(r'([\d\.]+)\s*mm\s*depth', full_report_text, re.IGNORECASE)
                if area_match and depth_match and intervention_key.lower() == "pothole":
                    area_sqm = float(area_match.group(1))
                    depth_mm = float(depth_match.group(1))
                    depth_m = depth_mm / 1000
                    quantity_found = area_sqm * depth_m
                    print(f"  > Found Pothole: {area_sqm} sqm area, {depth_mm} mm depth. Volume: {quantity_found:.4f} m^3")
                else: quantity_found = 0 

            # Specific Logic for Road Studs
            is_road_studs = intervention_key.lower() == "road studs"
            chainage_match = None
            if is_road_studs:
                chainage_match = re.search(r'(\d+)\+(\d+)\s+to\s+(\d+)\+(\d+)', full_report_text, re.IGNORECASE)
                if chainage_match:
                    start_km, start_m, end_km, end_m = map(int, chainage_match.groups())
                    length_m = abs(((end_km * 1000) + end_m) - ((start_km * 1000) + start_m))
                    print(f"  > Found chainage for road studs: {start_km}+{start_m} to {end_km}+{end_m}. Length: {length_m}m")
                    studs_per_edge = math.ceil(length_m / 9.0) 
                    quantity_found = studs_per_edge * 2 
                    print(f"  > Calculated studs needed: {quantity_found} studs")
                    unit_type = "item" 
                    # Adjust spec in memory for calculation
                    if "materials_per_meter" in specs: 
                        # Use a temporary copy to avoid modifying original spec_database
                        current_specs = specs.copy() 
                        current_specs["materials_per_item"] = current_specs.pop("materials_per_meter")
                        current_specs["materials_per_item"][0]["quantity"] = 1
                        specs = current_specs # Use the temp copy for this iteration
                else: # Default if no chainage found
                    print("  > Could not find chainage for road studs. Defaulting.")
                    unit_type = "item"; quantity_found = 1
                    if "materials_per_meter" in specs:
                         # Use a temporary copy
                        current_specs = specs.copy()
                        current_specs["materials_per_item"] = current_specs.pop("materials_per_meter")
                        current_specs["materials_per_item"][0]["quantity"] = 1
                        specs = current_specs

            print(f"Using Quantity: {quantity_found} {unit_type}(s)")
            report_file.write(f"  Quantity Found: {quantity_found} {unit_type}(s)\n")
            report_file.write(f"  Source Clause: {specs['source_clause']}\n")
            report_file.write("  Cost Breakdown:\n")

            # --- Calculate Cost ---
            item_total_cost = 0
            cost_breakdown_terminal = [] # For terminal output

            materials_list = (specs.get("materials_per_item", []) + 
                              specs.get("materials_per_meter", []) + 
                              specs.get("materials_per_cubic_meter", []))

            for material in materials_list:
                mat_name = material["name"]
                mat_qty_per_unit = material["quantity"]
                
                mat_qty_needed = mat_qty_per_unit * quantity_found
                
                line_output_file = "" # For file
                line_output_terminal = "" # For terminal
                if mat_name in price_database:
                    mat_price_per_unit = price_database[mat_name]
                    line_cost = mat_qty_needed * mat_price_per_unit
                    item_total_cost += line_cost
                    
                    line_output_file = f"    - {mat_name}: {mat_qty_needed:.2f} units @ ₹{mat_price_per_unit:.2f}/unit = ₹{line_cost:.2f}\n"
                    line_output_terminal = f"  - {mat_name}: {mat_qty_needed:.2f} units @ ₹{mat_price_per_unit:.2f}/unit = ₹{line_cost:.2f}"
                else:
                    line_output_file = f"    - {mat_name}: {mat_qty_needed:.2f} units @ PRICE NOT FOUND\n"
                    line_output_terminal = f"  - {mat_name}: {mat_qty_needed:.2f} units @ PRICE NOT FOUND"
                
                report_file.write(line_output_file)
                cost_breakdown_terminal.append(line_output_terminal)
            
            # Print to terminal
            print(f"Cost Breakdown (Source: {specs['source_clause']}):") # Use potentially modified specs here
            for line in cost_breakdown_terminal: print(line)
            print(f"TOTAL for this item: ₹{item_total_cost:.2f}")

            report_file.write(f"  TOTAL for {intervention_key}: ₹{item_total_cost:.2f}\n\n")
            
            total_project_cost += item_total_cost

    # Write Final Summary to File
    report_file.write("-----------------------------------------\n")
    report_file.write("             SUMMARY\n")
    report_file.write("-----------------------------------------\n")
    report_file.write(f"TOTAL ESTIMATED MATERIAL COST: ₹{total_project_cost:.2f}\n")
    report_file.write("-----------------------------------------\n")
    report_file.write("(Note: Excludes labor, installation, taxes, etc.)\n")

print("\n--- ESTIMATION COMPLETE ---")
print(f"TOTAL PROJECT MATERIAL COST: ₹{total_project_cost:.2f}")
print(f"\nDetailed cost report saved to: {report_filename}")