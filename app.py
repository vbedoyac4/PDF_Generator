import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
import re
import io
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from PyPDF2 import PdfReader, PdfWriter
import os

# Configuración de la página
st.set_page_config(page_title="Herramientas PDF Integradas", layout="wide")

# ==========================================
# FUNCIONES: CÓDIGO 1 (Map Generator)
# ==========================================
def extract_customer_name_from_bytes(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page1 = doc.load_page(0)
    label = "Customer’s Last Name, First Name"
    hits = page1.search_for(label)
    if not hits:
        doc.close()
        return ""
    label_rect = hits[0]
    candidate = ""
    best_y = -1
    pagedict = page1.get_text("dict")
    for block in pagedict.get("blocks", []):
        if "lines" not in block: continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if "," in text:
                    y1_span = span["bbox"][3]
                    if y1_span < label_rect.y0 and y1_span > best_y:
                        best_y = y1_span
                        candidate = text
    doc.close()
    if not candidate: return ""
    partes = [p.strip() for p in candidate.split(",", 1)]
    if len(partes) == 2:
        last, first = partes
        return f"{first} {last}"
    return ""

def process_pdf_bytes_map(pdf_bytes, customer_name, additional_notes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page1 = doc.load_page(0)
    page3 = doc.load_page(2)
    filename = f"{customer_name} Map.pdf"

    # 1) REDACTAR EMAIL PÁGINA 1
    pagedict1 = page1.get_text("dict")
    for block in pagedict1.get("blocks", []):
        if "lines" not in block: continue
        for line in block["lines"]:
            for span in line["spans"]:
                if "@" in span["text"]:
                    x0, y0, x1, y1 = span["bbox"]
                    redact_rect = fitz.Rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2)
                    page1.add_redact_annot(redact_rect, fill=(1, 1, 1))
    page1.apply_redactions()

    # 2) REDACTAR PAGO PÁGINA 3
    start_text = "Payment Schedule: You agree that payments will be due as indicated below"
    end_text = "Superior Authorized Representative"
    start_hits = page3.search_for(start_text)
    end_hits = page3.search_for(end_text)

    if start_hits and end_hits:
        start_rect = start_hits[0]
        end_rect = end_hits[0]
        redact_block = fitz.Rect(0, start_rect.y0 - 2, page3.rect.width, end_rect.y1 + 2)
        page3.add_redact_annot(redact_block, fill=(1, 1, 1))
        page3.apply_redactions()

        # 3) INSERTAR NOTAS
        phrase = "It is very important for you to read and understand"
        phrase_hits = page3.search_for(phrase)
        align_x = phrase_hits[0].x0 if phrase_hits else redact_block.x0 + 72

        header_text = "Additional Notes:"
        header_y = redact_block.y0 + 20
        page3.insert_text((align_x, header_y), header_text, fontname="Helvetica-Bold", fontsize=10)

        body_y = header_y + 10 + 4
        for idx, line in enumerate(additional_notes.split("\n")):
            line_text = line.strip()
            if not line_text: continue
            page3.insert_text((align_x, body_y + idx * 10), line_text, fontname="Helvetica", fontsize=8)

    new_doc = fitz.open()
    new_doc.insert_pdf(doc, from_page=0, to_page=0)
    new_doc.insert_pdf(doc, from_page=2, to_page=2)
    
    pdf_output = io.BytesIO()
    new_doc.save(pdf_output)
    new_doc.close()
    doc.close()
    pdf_output.seek(0)
    return pdf_output, filename

# ==========================================
# FUNCIONES: CÓDIGO 2 (Pick Ticket)
# ==========================================
def extract_text_from_pdf(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages_text = []
    for page_num in range(doc.page_count):
        page = doc.load_page(page_num)
        text = page.get_text()
        pages_text.append(text)
    doc.close()
    return pages_text

def extract_header_info(pages_text):
    header_info = {'title': '', 'customer': '', 'date': '', 'notes': '', 'job_number': '', 'sales_order': '', 'full_header': ''}
    if not pages_text: return header_info
    first_page = pages_text[0]
    lines = first_page.split('\n')
    header_lines = []
    for line in lines:
        if 'BoM Drawing' in line: break
        if line.strip(): header_lines.append(line)
    header_info['full_header'] = '\n'.join(header_lines)
    for line in lines:
        line_lower = line.lower()
        if 'pick ticket' in line_lower and not header_info['title']: header_info['title'] = line.strip()
        elif 'customer:' in line_lower:
            parts = line.split(':', 1)
            if len(parts) > 1: header_info['customer'] = parts[1].strip()
        elif 'pick ticket generated:' in line_lower or 'generated:' in line_lower:
            parts = line.split(':', 1)
            if len(parts) > 1: header_info['date'] = parts[1].strip()
        elif 'notes:' in line_lower:
            parts = line.split(':', 1)
            if len(parts) > 1: header_info['notes'] = parts[1].strip()
        elif 'job #:' in line_lower or 'job:' in line_lower:
            parts = line.split(':', 1)
            if len(parts) > 1: header_info['job_number'] = parts[1].strip()
        elif 'sales order #:' in line_lower or 'sos sales order #:' in line_lower:
            parts = line.split(':', 1)
            if len(parts) > 1: header_info['sales_order'] = parts[1].strip()
    return header_info

def extract_groups_from_pdf(pages_text):
    all_groups = []
    for page_num, page_text in enumerate(pages_text):
        if page_num == 0: continue
        lines = page_text.split('\n')
        group_name = None
        group_name_idx = -1
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if 'Other Items' in line_stripped:
                group_name = line_stripped
                group_name_idx = i
                break
        
        if not group_name:
            for i, line in enumerate(lines):
                line_stripped = line.strip()
                if (line_stripped and ':' not in line_stripped and
                    not re.match(r'^\(?\d+(\.\d+)?\)?$', line_stripped) and
                    line_stripped.upper() != 'QTY' and 'Pick Ticket' not in line_stripped and
                    'Customer:' not in line_stripped and 'Generated:' not in line_stripped and
                    'Job #:' not in line_stripped and 'Sales Order #:' not in line_stripped and
                    len(line_stripped) > 3 and len(line_stripped) < 100):
                    
                    for j in range(i + 1, min(i + 10, len(lines))):
                        if lines[j].strip().upper() == 'QTY' or '|' in lines[j]:
                            group_name = line_stripped
                            group_name_idx = i
                            break
                    if group_name: break
        
        if not group_name: continue
        
        items = []
        i = group_name_idx + 1
        if i < len(lines) and lines[i].strip().upper() == 'QTY': i += 1
        
        while i < len(lines):
            current_line = lines[i].strip() if i < len(lines) else ""
            if re.match(r'^\(?\d+(\.\d+)?\)?$', current_line):
                qty_match = re.match(r'\(?(\d+(?:\.\d+)?)\)?', current_line)
                qty = qty_match.group(1) if qty_match else ""
                code = ""
                name = ""
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and not re.match(r'^\(?\d+(\.\d+)?\)?$', next_line):
                        code = next_line
                        if i + 2 < len(lines):
                            name_line = lines[i + 2].strip()
                            if name_line and not re.match(r'^\(?\d+(\.\d+)?\)?$', name_line):
                                name = name_line
                                i += 3
                            else:
                                name = code
                                i += 2
                        else:
                            name = code
                            i += 2
                    else:
                        code = "NS"
                        i += 1
                else:
                    code = "NS"
                    i += 1
                if qty: items.append((qty, code, name))
                continue
            elif re.match(r'^\d+(\.\d+)?$', current_line):
                qty = current_line
                code, name = "", ""
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and not re.match(r'^\d+(\.\d+)?$', next_line):
                        code = next_line
                        if i + 2 < len(lines):
                            name_line = lines[i + 2].strip()
                            if name_line and not re.match(r'^\d+(\.\d+)?$', name_line):
                                name = name_line
                                i += 3
                            else:
                                name = code
                                i += 2
                        else:
                            name = code
                            i += 2
                    else:
                        code = "NS"
                        i += 1
                else:
                    code = "NS"
                    i += 1
                if qty: items.append((qty, code, name))
                continue
            
            if ('---' in current_line or 'Page' in current_line or 'Job #:' in current_line or 'Sales Order #:' in current_line): break
            i += 1
        
        processed_items = []
        for qty, code, name in items:
            if not code or code.strip() == "": code = "NS"
            if not name and code and code != "NS": name = code
            processed_items.append((qty, code, name))
        
        unique_items = []
        seen = set()
        for qty, code, name in processed_items:
            key = (qty, code, name)
            if key not in seen:
                seen.add(key)
                unique_items.append((qty, code, name))
        if unique_items: all_groups.append((group_name, unique_items))
    return all_groups

def create_pdf_with_table(groups, header_info, original_pdf_bytes):
    buffer = BytesIO()
    try:
        original_pdf = fitz.open(stream=original_pdf_bytes, filetype="pdf")
        if original_pdf.page_count == 0:
            original_pdf.close()
            raise ValueError("The PDF does not contain pages.")
        new_pdf = fitz.open()
        new_pdf.insert_pdf(original_pdf, from_page=0, to_page=0)
        original_pdf.close()
        
        if new_pdf.page_count > 0:
            first_page = new_pdf[0]
            patterns = [r'\d+\s*/\s*\d+', r'\d+\s*of\s*\d+', r'Page\s*\d+\s*of\s*\d+', r'Página\s*\d+\s*de\s*\d+', r'\d+\s*-\s*\d+']
            text_instances = []
            for pattern in patterns:
                found = first_page.search_for(pattern)
                if found: text_instances.extend(found)
            for inst in text_instances:
                rect = fitz.Rect(inst.x0 - 2, inst.y0 - 2, inst.x1 + 2, inst.y1 + 2)
                first_page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)
            
            page_rect = first_page.rect
            search_area = fitz.Rect(0, page_rect.height - 100, page_rect.width, page_rect.height)
            for i in range(1, 20):
                found = first_page.search_for(str(i), clip=search_area)
                for inst in found:
                    rect = fitz.Rect(inst.x0 - 2, inst.y0 - 2, inst.x1 + 2, inst.y1 + 2)
                    first_page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)
    except Exception as e:
        st.warning(f"Warning when processing page 1: {e}. Creating new PDF from scratch.")
        new_pdf = fitz.open()
    
    table_buffer = BytesIO()
    doc = SimpleDocTemplate(table_buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.75*inch, leftMargin=0.5*inch, rightMargin=0.5*inch)
    styles = getSampleStyleSheet()
    elements = []
    table_data = []
    header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontSize=9, textColor=colors.white, alignment=1, fontName='Helvetica-Bold')
    group_header_style = ParagraphStyle('GroupHeaderStyle', parent=styles['Normal'], fontSize=10, alignment=1, fontName='Helvetica-Bold', textColor=colors.white, spaceBefore=12, spaceAfter=6)
    
    for group_idx, (group_name, items) in enumerate(groups):
        group_header = Paragraph(f"{group_name}", group_header_style)
        table_data.append([group_header, '', '', '', '', ''])
        table_data.append([
            Paragraph('Qty', header_style), Paragraph('Code', header_style), Paragraph('Name', header_style),
            Paragraph('Packing', header_style), Paragraph('Checking', header_style), Paragraph('Installer', header_style)
        ])
        for qty, code, name in items:
            if not name and code and code != "NS": name = code
            qty_para = Paragraph(qty, ParagraphStyle('QtyStyle', alignment=1, fontSize=9))
            code_para = Paragraph(code, ParagraphStyle('CodeStyle', fontSize=9))
            name_para = Paragraph(name, ParagraphStyle('NameStyle', fontSize=9, leading=11))
            table_data.append([qty_para, code_para, name_para, Paragraph('', ParagraphStyle('EmptyStyle', alignment=1, fontSize=9)), Paragraph('', ParagraphStyle('EmptyStyle', alignment=1, fontSize=9)), Paragraph('', ParagraphStyle('EmptyStyle', alignment=1, fontSize=9))])
        if group_idx < len(groups) - 1:
            table_data.append(['', '', '', '', '', ''])
            table_data.append(['', '', '', '', '', ''])

    col_widths = [0.5*inch, 1.5*inch, 3.5*inch, 0.8*inch, 0.8*inch, 0.8*inch]
    table = Table(table_data, colWidths=col_widths, repeatRows=0)
    table_style = TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey), ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'), ('ALIGN', (2, 0), (2, -1), 'LEFT'),
        ('ALIGN', (3, 0), (-1, -1), 'CENTER'), ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6), ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4), ('LEADING', (0, 0), (-1, -1), 11),
    ])
    
    row_idx = 0
    for group_idx, (group_name, items) in enumerate(groups):
        table_style.add('BACKGROUND', (0, row_idx), (5, row_idx), colors.HexColor('#A0A0A0'))
        table_style.add('TEXTCOLOR', (0, row_idx), (5, row_idx), colors.white)
        table_style.add('FONTNAME', (0, row_idx), (5, row_idx), 'Helvetica-Bold')
        table_style.add('FONTSIZE', (0, row_idx), (5, row_idx), 10)
        table_style.add('SPAN', (0, row_idx), (5, row_idx))
        table_style.add('ALIGN', (0, row_idx), (5, row_idx), 'CENTER')
        row_idx += 1
        table_style.add('BACKGROUND', (0, row_idx), (5, row_idx), colors.HexColor('#808080'))
        table_style.add('TEXTCOLOR', (0, row_idx), (5, row_idx), colors.white)
        table_style.add('FONTNAME', (0, row_idx), (5, row_idx), 'Helvetica-Bold')
        table_style.add('FONTSIZE', (0, row_idx), (5, row_idx), 9)
        row_idx += 1
        row_idx += len(items)
        if group_idx < len(groups) - 1: row_idx += 2
    
    table.setStyle(table_style)
    elements.append(table)
    doc.build(elements)
    table_buffer.seek(0)
    
    table_pdf = fitz.open("pdf", table_buffer.read())
    for page_num in range(table_pdf.page_count):
        new_pdf.insert_pdf(table_pdf, from_page=page_num, to_page=page_num)
    table_pdf.close()
    
    total_pages = new_pdf.page_count
    for page_num in range(total_pages):
        page = new_pdf[page_num]
        page_rect = page.rect
        bottom_area = fitz.Rect(0, page_rect.height - 100, page_rect.width, page_rect.height)
        patterns_to_clean = [r'\d+\s*/\s*\d+', r'\d+\s*of\s*\d+', r'Page\s*\d+\s*of\s*\d+', r'Página\s*\d+\s*de\s*\d+', r'\d+\s*-\s*\d+']
        for pattern in patterns_to_clean:
            found = page.search_for(pattern, clip=bottom_area)
            for inst in found:
                rect = fitz.Rect(inst.x0 - 10, inst.y0 - 5, inst.x1 + 10, inst.y1 + 5)
                page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)
        for i in range(1, total_pages + 1):
            found = page.search_for(str(i), clip=bottom_area)
            for inst in found:
                if inst.y1 > page_rect.height - 50:
                    rect = fitz.Rect(inst.x0 - 5, inst.y0 - 5, inst.x1 + 5, inst.y1 + 5)
                    page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)
        
        center_x = page_rect.width / 2
        bottom_y = page_rect.height - 40
        text = f"{page_num + 1} / {total_pages}"
        approx_char_width = 4.5
        text_width = len(text) * approx_char_width
        x_position = center_x - (text_width / 2)
        page.insert_text(point=(x_position, bottom_y), text=text, fontsize=9, color=(0, 0, 0), fontname="Helvetica")
    
    new_pdf.save(buffer)
    new_pdf.close()
    buffer.seek(0)
    return buffer

def clean_filename_pick_ticket(text):
    if not text: return ""
    text = text.replace('/', '_').replace('\\', '_').replace(':', '_')
    text = text.replace('*', '_').replace('?', '_').replace('"', '_')
    text = text.replace('<', '_').replace('>', '_').replace('|', '_')
    text = ' '.join(text.split())
    if len(text) > 100: text = text[:100]
    return text

# ==========================================
# INTERFAZ UNIFICADA
# ==========================================

st.title("🛠️ Centro de Gestión de PDF")

# Dividir en 2 columnas para Funciones 1 y 2
col1, col2 = st.columns(2)

# --- COLUMNA 1: MAP GENERATOR ---
with col1:
    st.header("1. PDF Map Generator")
    uploaded_file1 = st.file_uploader("Upload PDF (Map)", type="pdf", key="u1")
    
    if uploaded_file1:
        pdf_bytes = uploaded_file1.read()
        detected_name = extract_customer_name_from_bytes(pdf_bytes)

        if detected_name:
            st.text_input("Detected Customer Name", value=detected_name, disabled=True, key="detected_name_1")
            customer_name = detected_name
        else:
            customer_name = st.text_input("Customer Name (enter as 'First Last')", value="", key="manual_name_1")

        additional_notes = st.text_area("Additional Notes (optional):", key="notes_1")

        if st.button("Generate Map PDF"):
            final_name = customer_name if detected_name else st.session_state.manual_name_1
            if not final_name:
                st.error("Please provide the customer name.")
            else:
                try:
                    pdf_output, filename = process_pdf_bytes_map(pdf_bytes, final_name, additional_notes)
                    st.download_button(
                        label="Download Modified PDF",
                        data=pdf_output,
                        file_name=filename,
                        mime="application/pdf"
                    )
                except Exception as e:
                    st.error(f"Error processing PDF: {e}")

# --- COLUMNA 2: PICK TICKET PROCESSOR ---
with col2:
    st.header("2. Pick Ticket Processor")
    uploaded_file2 = st.file_uploader("Upload Pick Ticket", type="pdf", key="u2")
    
    if uploaded_file2:
        if st.button("Generate Pick Ticket"):
            try:
                pdf_bytes2 = uploaded_file2.read()
                pages_text = extract_text_from_pdf(pdf_bytes2)
                header_info = extract_header_info(pages_text)
                groups = extract_groups_from_pdf(pages_text)
                
                new_pdf_buffer = create_pdf_with_table(groups, header_info, pdf_bytes2)
                
                # Lógica de nombre EXACTA del código 2
                customer = header_info.get('customer', '').strip()
                job_number = header_info.get('job_number', '').strip()
                clean_customer = clean_filename_pick_ticket(customer)
                clean_job_number = clean_filename_pick_ticket(job_number)
                
                if clean_customer and clean_job_number:
                    filename2 = f"{clean_customer} Job# {clean_job_number} Pick Ticket.pdf"
                elif clean_customer:
                    filename2 = f"{clean_customer} Pick Ticket.pdf"
                elif clean_job_number:
                    filename2 = f"Job# {clean_job_number} Pick Ticket.pdf"
                else:
                    filename2 = f"Pick Ticket {uploaded_file2.name}"
                
                # Guardar en session_state para que el botón no desaparezca
                st.session_state['pt_buffer'] = new_pdf_buffer
                st.session_state['pt_name'] = filename2
                st.success(f"✅ Pick Ticket Generado: {len(groups)} grupos encontrados.")

            except Exception as e:
                st.error(f"Error processing PDF: {e}")
        
        # Botón de descarga persistente
        if 'pt_buffer' in st.session_state:
            st.download_button(
                label="Download Pick Ticket PDF",
                data=st.session_state['pt_buffer'],
                file_name=st.session_state['pt_name'],
                mime="application/pdf",
                key="dl_btn_2"
            )

st.markdown("---")

# --- FILA INFERIOR: REMOVE PAGES ---
st.header("3. Eliminar Páginas de PDF")
uploaded_file3 = st.file_uploader("Upload PDF para recortar", type="pdf", key="u3")

if uploaded_file3:
    # Mostramos información básica
    try:
        reader = PdfReader(uploaded_file3)
        total_pages = len(reader.pages)
        st.info(f"El PDF tiene {total_pages} páginas.")
        
        # Input para páginas
        pages_input = st.text_input("Ingresa los números de las páginas que quieres eliminar (ej: 2,4,7):", key="pg_rem")
        
        if st.button("Eliminar Páginas"):
            if not pages_input:
                st.warning("Por favor ingresa números de página.")
            else:
                try:
                    # Lógica igual al código 3 (PyPDF2)
                    pages_to_remove = [int(p.strip()) - 1 for p in pages_input.split(",") if p.strip().isdigit()]
                    
                    writer = PdfWriter()
                    # Recargar el reader desde cero para asegurar integridad (Streamlit a veces consume el buffer)
                    uploaded_file3.seek(0)
                    reader = PdfReader(uploaded_file3)
                    
                    for i, page in enumerate(reader.pages):
                        if i not in pages_to_remove:
                            writer.add_page(page)
                    
                    out_buffer3 = BytesIO()
                    writer.write(out_buffer3)
                    out_buffer3.seek(0)
                    
                    # Nombre del archivo igual al original + sufijo (Lógica código 3)
                    original_name = uploaded_file3.name
                    # El código 3 usaba os.path.splitext, aquí lo simulamos:
                    base_name = os.path.splitext(original_name)[0]
                    final_name3 = f"{base_name}_sin_paginas.pdf"
                    
                    st.session_state['rem_buffer'] = out_buffer3
                    st.session_state['rem_name'] = final_name3
                    st.success("PDF procesado correctamente.")
                    
                except Exception as e:
                    st.error(f"Error: {e}")

        # Botón de descarga persistente
        if 'rem_buffer' in st.session_state:
            st.download_button(
                label=f"Descargar {st.session_state['rem_name']}",
                data=st.session_state['rem_buffer'],
                file_name=st.session_state['rem_name'],
                mime="application/pdf",
                key="dl_btn_3"
            )

    except Exception as e:
        st.error(f"Error leyendo el archivo: {e}")
