import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
import re
from io import BytesIO
import sys
import subprocess
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch

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
    header_info = {
        'title': '',
        'customer': '',
        'date': '',
        'notes': '',
        'job_number': '',
        'sales_order': '',
        'full_header': ''
    }
    
    if not pages_text:
        return header_info
    
    first_page = pages_text[0]
    lines = first_page.split('\n')
    
    header_lines = []
    for line in lines:
        if 'BoM Drawing' in line:
            break
        if line.strip():
            header_lines.append(line)
    
    header_info['full_header'] = '\n'.join(header_lines)
    
    for line in lines:
        line_lower = line.lower()
        
        if 'pick ticket' in line_lower and not header_info['title']:
            header_info['title'] = line.strip()
        elif 'customer:' in line_lower:
            parts = line.split(':', 1)
            if len(parts) > 1:
                header_info['customer'] = parts[1].strip()
        elif 'pick ticket generated:' in line_lower or 'generated:' in line_lower:
            parts = line.split(':', 1)
            if len(parts) > 1:
                header_info['date'] = parts[1].strip()
        elif 'notes:' in line_lower:
            parts = line.split(':', 1)
            if len(parts) > 1:
                header_info['notes'] = parts[1].strip()
        elif 'job #:' in line_lower or 'job:' in line_lower:
            parts = line.split(':', 1)
            if len(parts) > 1:
                header_info['job_number'] = parts[1].strip()
        elif 'sales order #:' in line_lower or 'sos sales order #:' in line_lower:
            parts = line.split(':', 1)
            if len(parts) > 1:
                header_info['sales_order'] = parts[1].strip()
    
    return header_info

def extract_groups_from_pdf(pages_text):
   
    all_groups = []
    
    for page_num, page_text in enumerate(pages_text):
        if page_num == 0:
            continue
            
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
                
                if (line_stripped and 
                    ':' not in line_stripped and
                    not re.match(r'^\(?\d+(\.\d+)?\)?$', line_stripped) and  # Modificado para decimales
                    line_stripped.upper() != 'QTY' and
                    'Pick Ticket' not in line_stripped and
                    'Customer:' not in line_stripped and
                    'Generated:' not in line_stripped and
                    'Job #:' not in line_stripped and
                    'Sales Order #:' not in line_stripped and
                    len(line_stripped) > 3 and len(line_stripped) < 100):
                    
                    for j in range(i + 1, min(i + 10, len(lines))):
                        if lines[j].strip().upper() == 'QTY' or '|' in lines[j]:
                            group_name = line_stripped
                            group_name_idx = i
                            break
                    
                    if group_name:
                        break
        
        if not group_name:
            continue
        
        items = []
        i = group_name_idx + 1
        
        if i < len(lines) and lines[i].strip().upper() == 'QTY':
            i += 1
        
        while i < len(lines):
            current_line = lines[i].strip() if i < len(lines) else ""
            
            # Modificado para aceptar decimales
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
                        # Si no hay código, usar "NS"
                        code = "NS"
                        i += 1 
                else:
                    # Si no hay código, usar "NS"
                    code = "NS"
                    i += 1 
                
                if qty:
                    items.append((qty, code, name))
                continue
            
            # Modificado para aceptar decimales
            elif re.match(r'^\d+(\.\d+)?$', current_line):
                qty = current_line
                code = ""
                name = ""
                
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
                        # Si no hay código, usar "NS"
                        code = "NS"
                        i += 1
                else:
                    # Si no hay código, usar "NS"
                    code = "NS"
                    i += 1
                
                if qty:
                    items.append((qty, code, name))
                continue
            
            if ('---' in current_line or 
                'Page' in current_line or
                'Job #:' in current_line or
                'Sales Order #:' in current_line):
                break
            
            i += 1
        
        # Asegurar que los items sin código tengan "NS"
        processed_items = []
        for qty, code, name in items:
            if not code or code.strip() == "":
                code = "NS"
            if not name and code and code != "NS":
                name = code
            processed_items.append((qty, code, name))
        
        unique_items = []
        seen = set()
        for qty, code, name in processed_items:
            key = (qty, code, name)
            if key not in seen:
                seen.add(key)
                unique_items.append((qty, code, name))
        
        if unique_items:
            all_groups.append((group_name, unique_items))
    
    return all_groups

def create_pdf_with_table(groups, header_info, original_pdf_bytes):
    buffer = BytesIO()
    
    # Crear el PDF con la primera página original
    try:
        original_pdf = fitz.open(stream=original_pdf_bytes, filetype="pdf")
        
        if original_pdf.page_count == 0:
            original_pdf.close()
            raise ValueError("The PDF does not contain pages.")
        
        new_pdf = fitz.open()
        # Insertar solo la primera página del original
        new_pdf.insert_pdf(original_pdf, from_page=0, to_page=0)
        original_pdf.close()
        
        # Limpiar números de página en la primera página
        if new_pdf.page_count > 0:
            first_page = new_pdf[0]
            
            # Patrones comunes de numeración de páginas
            patterns = [
                r'\d+\s*/\s*\d+',  
                r'\d+\s*of\s*\d+', 
                r'Page\s*\d+\s*of\s*\d+', 
                r'Página\s*\d+\s*de\s*\d+', 
                r'\d+\s*-\s*\d+', 
            ]
            
            text_instances = []
            for pattern in patterns:
                found = first_page.search_for(pattern)
                if found:
                    text_instances.extend(found)
            
            for inst in text_instances:
                rect = fitz.Rect(inst.x0 - 2, inst.y0 - 2, inst.x1 + 2, inst.y1 + 2)
                first_page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)
            
            # Limpiar cualquier número en la parte inferior
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
    
    # Crear el PDF de la tabla
    table_buffer = BytesIO()
    
    doc = SimpleDocTemplate(
        table_buffer, 
        pagesize=letter,
        topMargin=0.5*inch,
        bottomMargin=0.75*inch,
        leftMargin=0.5*inch,
        rightMargin=0.5*inch
    )
    
    styles = getSampleStyleSheet()
    elements = []
    
    table_data = []
    
    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.white,
        alignment=1,
        fontName='Helvetica-Bold'
    )
    
    group_header_style = ParagraphStyle(
        'GroupHeaderStyle',
        parent=styles['Normal'],
        fontSize=10,
        alignment=1,
        fontName='Helvetica-Bold',
        textColor=colors.white,
        spaceBefore=12,
        spaceAfter=6
    )
    
    for group_idx, (group_name, items) in enumerate(groups):
        group_header = Paragraph(f"{group_name}", group_header_style)
        table_data.append([group_header, '', '', '', '', ''])
        
        table_data.append([
            Paragraph('Qty', header_style),
            Paragraph('Code', header_style),
            Paragraph('Name', header_style),
            Paragraph('Packing', header_style),
            Paragraph('Checking', header_style),
            Paragraph('Installer', header_style)
        ])
        
        for qty, code, name in items:
            if not name and code and code != "NS":
                name = code
            
            qty_para = Paragraph(qty, ParagraphStyle('QtyStyle', alignment=1, fontSize=9))
            code_para = Paragraph(code, ParagraphStyle('CodeStyle', fontSize=9))
            name_para = Paragraph(name, ParagraphStyle('NameStyle', fontSize=9, leading=11))
            
            table_data.append([
                qty_para,
                code_para,
                name_para,
                Paragraph('', ParagraphStyle('EmptyStyle', alignment=1, fontSize=9)),
                Paragraph('', ParagraphStyle('EmptyStyle', alignment=1, fontSize=9)),
                Paragraph('', ParagraphStyle('EmptyStyle', alignment=1, fontSize=9))
            ])
        
        if group_idx < len(groups) - 1:
            table_data.append(['', '', '', '', '', ''])
            table_data.append(['', '', '', '', '', ''])

    col_widths = [0.5*inch, 1.5*inch, 3.5*inch, 0.8*inch, 0.8*inch, 0.8*inch]
    table = Table(table_data, colWidths=col_widths, repeatRows=0)
    
    table_style = TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('ALIGN', (2, 0), (2, -1), 'LEFT'),
        ('ALIGN', (3, 0), (-1, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEADING', (0, 0), (-1, -1), 11),
    ])
    
    row_idx = 0
    for group_idx, (group_name, items) in enumerate(groups):
        # Nombre del grupo
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
        
        if group_idx < len(groups) - 1:
            row_idx += 2
    
    table.setStyle(table_style)
    elements.append(table)
    
    # Construir el documento de la tabla
    doc.build(elements)
    table_buffer.seek(0)
    
    # Insertar las páginas de la tabla en el nuevo PDF
    table_pdf = fitz.open("pdf", table_buffer.read())
    for page_num in range(table_pdf.page_count):
        new_pdf.insert_pdf(table_pdf, from_page=page_num, to_page=page_num)
    table_pdf.close()
    
    # Ahora añadir la numeración correcta a TODAS las páginas
    total_pages = new_pdf.page_count
    
    for page_num in range(total_pages):
        page = new_pdf[page_num]
        page_rect = page.rect
        
        # Limpiar cualquier numeración existente en la parte inferior
        bottom_area = fitz.Rect(0, page_rect.height - 100, page_rect.width, page_rect.height)
        
        # Buscar y eliminar cualquier texto que parezca una numeración de página
        patterns_to_clean = [
            r'\d+\s*/\s*\d+',
            r'\d+\s*of\s*\d+',
            r'Page\s*\d+\s*of\s*\d+',
            r'Página\s*\d+\s*de\s*\d+',
            r'\d+\s*-\s*\d+',
        ]
        
        for pattern in patterns_to_clean:
            found = page.search_for(pattern, clip=bottom_area)
            for inst in found:
                # Crear un rectángulo un poco más grande que el texto encontrado
                rect = fitz.Rect(inst.x0 - 10, inst.y0 - 5, inst.x1 + 10, inst.y1 + 5)
                page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)
        
        # También limpiar números individuales en el área inferior
        for i in range(1, total_pages + 1):
            found = page.search_for(str(i), clip=bottom_area)
            for inst in found:
                if inst.y1 > page_rect.height - 50:  # Solo en la parte inferior
                    rect = fitz.Rect(inst.x0 - 5, inst.y0 - 5, inst.x1 + 5, inst.y1 + 5)
                    page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)
        
        # Añadir la numeración correcta
        center_x = page_rect.width / 2
        bottom_y = page_rect.height - 40  # Un poco más arriba del borde inferior
        
        text = f"{page_num + 1} / {total_pages}"
        
        # Calcular posición X para centrar el texto
        # Usamos una aproximación del ancho del texto (aproximadamente 4.5 puntos por carácter)
        approx_char_width = 4.5
        text_width = len(text) * approx_char_width
        x_position = center_x - (text_width / 2)
        
        page.insert_text(
            point=(x_position, bottom_y),
            text=text,
            fontsize=9,
            color=(0, 0, 0),
            fontname="Helvetica"
        )
    
    # Guardar el PDF final
    new_pdf.save(buffer)
    new_pdf.close()
    
    buffer.seek(0)
    return buffer

def main():
    st.set_page_config(page_title="Procesador de Pick Tickets", layout="wide")
    
    st.title("📋 Procesador de Pick Tickets")
   
    uploaded_file = st.file_uploader("Sube tu PDF de Pick Ticket", type=["pdf"])
    
    if uploaded_file is not None:
        file_name = uploaded_file.name
        
        with st.spinner(f"Analyzing {file_name}..."):
            try:

                pdf_bytes = uploaded_file.read()
                pages_text = extract_text_from_pdf(pdf_bytes)
                header_info = extract_header_info(pages_text)
                groups = extract_groups_from_pdf(pages_text)
                
                total_items = sum(len(items) for _, items in groups) if groups else 0
                
                st.success(f"✅ Processed: {len(pages_text)} pages, {len(groups)} groups, {total_items} items")
                
            except Exception as e:
                st.error(f"❌ Error processing PDF: {e}")
                return
            
            st.subheader("🔄 Generate PDF")
            
            if st.button("✨ Generate PDF", type="primary", use_container_width=True):
                with st.spinner("Creating PDF..."):
                    try:
                        new_pdf = create_pdf_with_table(groups, header_info, pdf_bytes)
                        
                        def clean_filename(text):
                            if not text:
                                return ""

                            text = text.replace('/', '_').replace('\\', '_').replace(':', '_')
                            text = text.replace('*', '_').replace('?', '_').replace('"', '_')
                            text = text.replace('<', '_').replace('>', '_').replace('|', '_')
                            text = ' '.join(text.split())

                            if len(text) > 100:
                                text = text[:100]
                            return text
                        
                        customer = header_info.get('customer', '').strip()
                        job_number = header_info.get('job_number', '').strip()
                        
                        clean_customer = clean_filename(customer)
                        clean_job_number = clean_filename(job_number)
                        
                        if clean_customer and clean_job_number:
                            filename = f"{clean_customer} Job# {clean_job_number} Pick Ticket.pdf"
                        elif clean_customer:
                            filename = f"{clean_customer} Pick Ticket.pdf"
                        elif clean_job_number:
                            filename = f"Job# {clean_job_number} Pick Ticket.pdf"
                        else:
                            filename = f"Pick Ticket {file_name}"
                        
                        st.info(f"📄 The file will be saved as: **{filename}**")
                        
                        st.download_button(
                            label=f"⬇️ Download PDF ({total_items} items)",
                            data=new_pdf,
                            file_name=filename,
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True
                        )
                        
                        st.success("✅ PDF generated successfully!")
                        
                    except Exception as e:
                        st.error(f"❌ Error creating PDF: {e}")
                        st.info("💡 If the problem persists, try another PDF file.")
    
if __name__ == "__main__":
    main()
