from __future__ import annotations


def parse_policy_markdown(markdown_text: str) -> list[dict]:
    """Parse policy markdown file into chunks grouped by H2 and H3 headers.
    
    Each chunk contains:
    - section_h2: Name of the H2 heading (with '#' stripped)
    - section_h3: Name of the H3 heading (with '#' stripped, or None)
    - citation: Formatted citation like 'policy_mock_vi.md > Section H2 > Section H3'
    - rendered_text: Full context markdown text (H2 + H3 + Content)
    """
    lines = markdown_text.splitlines()
    chunks = []
    
    current_h2 = None
    current_h3 = None
    current_content_lines = []

    def emit_chunk():
        if not current_h2:
            return
        
        # Join content and strip outer whitespace
        content_text = "\n".join(current_content_lines).strip()
        if not content_text:
            return
            
        sec_h2 = current_h2.lstrip("#").strip()
        sec_h3 = current_h3.lstrip("#").strip() if current_h3 else None
        
        # Build citation
        if sec_h3:
            citation = f"policy_mock_vi.md > {sec_h2} > {sec_h3}"
            rendered_text = f"## {sec_h2}\n### {sec_h3}\n{content_text}"
        else:
            citation = f"policy_mock_vi.md > {sec_h2}"
            rendered_text = f"## {sec_h2}\n{content_text}"
            
        chunks.append({
            "section_h2": sec_h2,
            "section_h3": sec_h3,
            "citation": citation,
            "rendered_text": rendered_text
        })

    for line in lines:
        stripped_line = line.strip()
        
        if stripped_line.startswith("## "):
            emit_chunk()
            current_h2 = line
            current_h3 = None
            current_content_lines = []
        elif stripped_line.startswith("### "):
            emit_chunk()
            current_h3 = line
            current_content_lines = []
        elif stripped_line.startswith("# "):
            # Main title, ignore or treat as general text if needed (we ignore to avoid garbage chunks)
            pass
        else:
            # Accumulate normal content lines
            current_content_lines.append(line)

    # Emit the last chunk
    emit_chunk()
    
    return chunks
