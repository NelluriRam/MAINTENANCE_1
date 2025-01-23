from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas
import os
from pathlib import Path
from typing import List, Optional
from supabase import create_client, Client
import re

# Create FastAPI app
app = FastAPI(title="Maintenance Work Order System")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Supabase client (replace with environment variables in production)
supabase: Client = create_client(
    "https://qjgrdgerkpxfqshfnocw.supabase.co",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFqZ3JkZ2Vya3B4ZnFzaGZub2N3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Mzc2Njk1MjQsImV4cCI6MjA1MzI0NTUyNH0.c_wJ3VOu1N8Intfu5yDD4HcOjt0gORr6Kg1S8sUYLIE"
)

# Create directories if they don't exist
REPORTS_DIR = Path("reports")
STATIC_DIR = Path("static")

for dir_path in [REPORTS_DIR, STATIC_DIR]:
    dir_path.mkdir(exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Pydantic models
class WorkOrder(BaseModel):
    property_code: str
    room_numbers: str
    work_orders: str
    completion_date: str

class RemoveWorkOrder(BaseModel):
    property_code: str
    room_number: str

def get_property_name(property_code: str) -> str:
    """Return property name based on code."""
    return {
        "NY198": "Comfort Inn & Suites",
        "NY345": "Quality Inn & Suites"
    }.get(property_code, "Unknown Property")

def clean_input(input_str: str) -> List[str]:
    """Clean and split input string, removing extra whitespaces."""
    return [item.strip() for item in re.split(r'[,;]+', input_str) if item.strip()]

@app.get("/")
async def read_root():
    """Serve the main HTML page."""
    return FileResponse("static/index.html")

@app.post("/api/work-orders")
async def create_work_order(work_order: WorkOrder):
    """Create new work orders."""
    try:
        # Clean and validate inputs
        room_numbers = clean_input(work_order.room_numbers)
        work_orders_list = clean_input(work_order.work_orders)

        # Validate input lists
        if len(room_numbers) != len(work_orders_list):
            raise HTTPException(
                status_code=400,
                detail="Number of rooms and work orders must match"
            )

        # Parse completion date
        try:
            completion_date = datetime.strptime(work_order.completion_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid date format. Use YYYY-MM-DD"
            )

        # Process each work order
        for room_number, work_order_text in zip(room_numbers, work_orders_list):
            # Check for existing work order
            existing_order = supabase.table("work_orders").select("*").eq(
                "property_code", work_order.property_code
            ).eq("room_number", room_number).execute()

            work_order_data = {
                "property_code": work_order.property_code,
                "room_number": room_number,
                "work_order": work_order_text,
                "completion_date": completion_date.strftime("%Y-%m-%d"),
                "status": "Pending",
                "best_room": False  # Default value
            }

            if existing_order.data:
                # Update existing work order
                supabase.table("work_orders").update(work_order_data).eq(
                    "id", existing_order.data[0]["id"]
                ).execute()
            else:
                # Create new work order
                supabase.table("work_orders").insert(work_order_data).execute()

        return {
            "status": "success",
            "message": f"Work orders for {len(room_numbers)} room(s) saved successfully"
        }

    except Exception as e:
        # Log the full error for server-side debugging
        print(f"Error creating work order: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/remove-work-order")
async def remove_work_order(remove_order: RemoveWorkOrder):
    """Remove a work order for a specific room."""
    try:
        result = supabase.table("work_orders").delete().eq("property_code", remove_order.property_code).eq(
            "room_number", remove_order.room_number).execute()

        if result.data:
            return {
                "status": "success",
                "message": f"Work order for room {remove_order.room_number} removed successfully"
            }
        else:
            raise HTTPException(
                status_code=404,
                detail=f"No work order found for room {remove_order.room_number}"
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/generate-report/{property_code}")
async def generate_report(property_code: str):
    """Generate PDF report for property work orders and display it inline."""
    try:
        # Get work orders from database
        result = supabase.table("work_orders").select("*").eq("property_code", property_code).order(
            "room_number").execute()

        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="No work orders found for this property"
            )

        # Prepare PDF file
        pdf_path = REPORTS_DIR / f"{property_code}_maintenance_report.pdf"
        property_name = get_property_name(property_code)

        # Create PDF
        c = canvas.Canvas(str(pdf_path), pagesize=landscape(letter))
        width, height = landscape(letter)

        # Add header
        c.setFont("Helvetica-Bold", 18)
        c.drawString(30, height - 50, f"Maintenance Report for {property_name}")
        c.setFont("Helvetica", 12)
        c.drawString(30, height - 70, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Draw header line
        c.line(30, height - 85, width - 30, height - 85)

        # Set up table headers
        c.setFont("Helvetica-Bold", 12)
        y_position = height - 120
        col_positions = [30, 130, 380, 530, 630]
        headers = ["Room", "Work Order", "Completion Date", "Status", "Best Room"]

        for pos, header in zip(col_positions, headers):
            c.drawString(pos, y_position, header)

        # Add line under headers
        c.line(30, y_position - 15, width - 30, y_position - 15)

        # Add work orders to PDF
        y_position -= 40
        c.setFont("Helvetica", 10)

        for work_order in result.data:
            if y_position < 50:  # New page if needed
                c.showPage()
                c.setFont("Helvetica", 10)
                y_position = height - 50

            # Write row data
            c.drawString(col_positions[0], y_position, work_order["room_number"])

            # Wrap work order text
            work_order_text = work_order["work_order"]
            words = work_order_text.split()
            lines = []
            current_line = []

            for word in words:
                current_line.append(word)
                if c.stringWidth(' '.join(current_line), "Helvetica", 10) > 230:
                    current_line.pop()
                    lines.append(' '.join(current_line))
                    current_line = [word]

            if current_line:
                lines.append(' '.join(current_line))

            # Draw wrapped text
            for i, line in enumerate(lines):
                c.drawString(col_positions[1], y_position - (i * 12), line)

            # Continue with other columns
            c.drawString(col_positions[2], y_position, work_order["completion_date"])
            c.drawString(col_positions[3], y_position, work_order["status"])
            c.drawString(col_positions[4], y_position, "Yes" if work_order["best_room"] else "No")

            y_position -= max(len(lines) * 12, 20)

        # Save PDF
        c.save()

        # Return PDF file with Content-Disposition: inline for browser display
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename={property_code}_maintenance_report.pdf"
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/work-orders/{property_code}")
async def get_work_orders(property_code: str):
    """Get all work orders for a property."""
    try:
        result = supabase.table("work_orders").select("*").eq("property_code", property_code).execute()

        work_orders = [{
            "room_number": wo["room_number"],
            "work_order": wo["work_order"],
            "completion_date": wo["completion_date"],
            "status": wo["status"],
            "best_room": "Yes" if wo["best_room"] else "No"
        } for wo in result.data]

        return {"work_orders": work_orders}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/edit-work-order")
async def edit_work_order(request: Request):
    """Edit an existing work order."""
    try:
        data = await request.json()
        property_code = data.get('property_code')
        room_number = data.get('room_number')
        work_order = data.get('work_order')
        completion_date = data.get('completion_date')

        if not all([property_code, room_number, work_order, completion_date]):
            raise HTTPException(status_code=400, detail="Missing required fields")

        try:
            completion_date = datetime.strptime(completion_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid date format. Use YYYY-MM-DD"
            )

        result = supabase.table("work_orders").update({
            "work_order": work_order,
            "completion_date": completion_date.strftime("%Y-%m-%d")
        }).eq("property_code", property_code).eq("room_number", room_number).execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Room not found")

        return {"status": "success", "message": "Work order updated successfully"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/update-room-status")
async def update_room_status(request: Request):
    """Update room status and best room designation."""
    try:
        data = await request.json()
        property_code = data.get('property_code')
        room_number = data.get('room_number')
        status = data.get('status')
        best_room = data.get('best_room', False)

        if not all([property_code, room_number, status]):
            raise HTTPException(status_code=400, detail="Missing required fields")

        result = supabase.table("work_orders").update({
            "status": status,
            "best_room": best_room == "Yes"
        }).eq("property_code", property_code).eq("room_number", room_number).execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Room not found")

        return {"status": "success", "message": "Room status updated successfully"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/test-db")
async def test_db():
    try:
        result = supabase.table("work_orders").select("*").limit(1).execute()
        return {"status": "success", "message": "Database connected!", "data": result.data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)