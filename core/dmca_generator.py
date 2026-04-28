"""
core/dmca_generator.py
----------------------
Auto-generates DMCA / Rights Compliance takedown notices for flagged content.
"""

import datetime as dt
from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import io

def generate_dmca_text(
    suspect_video: str,
    publisher_name: str,
    matched_flags: int,
    total_frames: int,
    similarity_pct: float,
    evidence_timestamps: list[str],
    infringing_url: str = "N/A",
    contact_name: str = "Lag_Launch Rights Team",
    contact_email: str = "legal@laglaunch.com",
    contact_address: str = "123 Security Blvd, Cyber City"
) -> str:
    """Generates a legally formatted DMCA takedown text."""
    date_str = dt.datetime.now().strftime("%B %d, %Y")
    
    evidence_list = "\n".join(f"  - Infringing content appears at suspect timestamp(s): {ts}" for ts in evidence_timestamps[:5])
    if len(evidence_timestamps) > 5:
        evidence_list += f"\n  - ... and {len(evidence_timestamps) - 5} other instances."

    template = f"""
NOTICE OF COPYRIGHT INFRINGEMENT (DMCA)

Date: {date_str}

To whom it may concern,

This notice is provided pursuant to the Digital Millennium Copyright Act (DMCA), 17 U.S.C. Section 512.
I am writing to notify you that your service is hosting material that infringes upon the exclusive copyright 
rights of my organization. 

 1. Identification of the copyrighted work claimed to have been infringed:
    The original, authenticated media assets officially registered under our Asset Protection platform.

 2. Identification of the material that is claimed to be infringing:
    Direct Link / URL: {infringing_url}
    Uploader: {publisher_name}
    File Identifier: {suspect_video}
    
 3. Evidence of Infringement:
    Our automated perceptual systems matched {similarity_pct}% ({matched_flags}/{total_frames} selected keyframes) 
    of the suspect content to our authenticated internal rights database via direct vector embeddings.

    Documented timestamps of infringement:
{evidence_list}

 4. Rights Holder Assertion:
    I have a good faith belief that the use of the material in the manner complained of is not authorized by the 
    copyright owner, its agent, or the law. The information in this notification is accurate, and under penalty 
    of perjury, I am authorized to act on behalf of the owner of an exclusive right that is allegedly infringed.

 5. Rights Holder Contact Information:
    Name: {contact_name}
    Email: {contact_email}
    Address: {contact_address}

 Please act expeditiously to remove or disable access to the infringing material.

 Sincerely,
 {contact_name}
 Enforcement Division
"""
    return template.strip()

def save_dmca(report_filename: str, dmca_text: str, base_dir: Path) -> Path:
    """Save the text to a .txt file in reports folder."""
    out_dir = base_dir / "reports" / "dmca_notices"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    safe_name = report_filename.replace(".json", "") + "_DMCA.txt"
    out_path = out_dir / safe_name
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(dmca_text)
        
    return out_path

def save_dmca_pdf(report_filename: str, dmca_text: str, base_dir: Path) -> Path:
    """Save the DMCA notice as a professional PDF."""
    out_dir = base_dir / "reports" / "dmca_notices"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    safe_name = report_filename.replace(".json", "") + "_DMCA.pdf"
    out_path = out_dir / safe_name
    
    c = canvas.Canvas(str(out_path), pagesize=LETTER)
    width, height = LETTER
    
    # Header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, "Asset Protection Rights Compliance Report")
    
    c.setLineWidth(1)
    c.line(50, height - 60, width - 50, height - 60)
    
    # Content
    c.setFont("Helvetica", 11)
    text_obj = c.beginText(50, height - 100)
    text_obj.setLeading(14)
    
    # Split text into lines to handle in PDF
    for line in dmca_text.split('\n'):
        # Basic line wrap check
        if len(line) > 90:
            words = line.split(' ')
            current_line = ""
            for word in words:
                if len(current_line + word) > 90:
                    text_obj.textLine(current_line)
                    current_line = word + " "
                else:
                    current_line += word + " "
            text_obj.textLine(current_line)
        else:
            text_obj.textLine(line)
            
    c.drawText(text_obj)
    
    # Footer
    c.setFont("Helvetica-Oblique", 9)
    c.drawRightString(width - 50, 30, f"Generated automatically via DAP AI Engine on {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    c.save()
    return out_path

