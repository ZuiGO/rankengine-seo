import os
import fitz


def extract_pdf_data(file_path: str) -> dict:
    if not os.path.exists(file_path):
        return {"error": "File not found"}

    doc = fitz.open(file_path)
    result = {
        "page_count": len(doc),
        "metadata": doc.metadata,
        "file_size": os.path.getsize(file_path),
        "pages": [],
        "text_chunks": [],
        "tables": [],
        "images": [],
        "statistics": {},
    }

    full_text = ""
    total_words = 0

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_text = page.get_text()
        full_text += f"\n--- Page {page_num + 1} ---\n{page_text}"
        words = len(page_text.split())
        total_words += words

        page_info = {
            "number": page_num + 1,
            "word_count": words,
            "text_length": len(page_text),
            "text_preview": page_text[:500],
        }

        tables = page.find_tables()
        page_tables = []
        for t_idx, tab in enumerate(tables):
            headers = tab.header.external_names if tab.header else []
            data_rows = []
            for row in tab.extract():
                data_rows.append([str(c) if c else "" for c in row])
            page_info["table_count"] = page_info.get("table_count", 0) + 1
            page_tables.append({
                "page": page_num + 1,
                "index": t_idx,
                "rows": len(data_rows),
                "cols": len(headers) if headers else (len(data_rows[0]) if data_rows else 0),
                "headers": headers if headers else [],
                "data": data_rows[:20],
                "data_preview": data_rows[:5],
            })

        result["tables"].extend(page_tables)
        page_info["tables_found"] = len(page_tables)

        image_list = page.get_images(full=True)
        page_images = []
        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            img_data = {
                "page": page_num + 1,
                "index": img_index,
                "width": base_image.get("width"),
                "height": base_image.get("height"),
                "format": base_image.get("ext"),
                "color_space": base_image.get("colorspace"),
                "size_bytes": len(base_image.get("image")),
            }
            page_images.append(img_data)

            result["images"].append(img_data)

        page_info["images_found"] = len(page_images)
        result["pages"].append(page_info)

    # Text chunks for vectorization
    chunk_size = 800
    words_list = full_text.split()
    for i in range(0, len(words_list), chunk_size):
        chunk = " ".join(words_list[i:i + chunk_size])
        if chunk.strip():
            result["text_chunks"].append({
                "index": len(result["text_chunks"]),
                "start_word": i,
                "word_count": len(chunk.split()),
                "text": chunk,
                "text_preview": chunk[:300],
            })

    result["statistics"] = {
        "total_words": total_words,
        "total_text_chunks": len(result["text_chunks"]),
        "total_tables": len(result["tables"]),
        "total_images_extracted": len(result["images"]),
        "total_characters": len(full_text),
    }
    result["text"] = full_text

    doc.close()
    return result
