import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from flask import Flask, request, jsonify, send_file, session, redirect, url_for
from src.engine.extractor import extract_text
from src.engine.deid import deidentify_text, save_redaction_log
from dotenv import load_dotenv
from functools import wraps

load_dotenv()

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("DEID_PASSWORD", "changeme") + "_session_secret"

UI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.html")
LOGIN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "login.html")

DEID_PASSWORD = os.environ.get("DEID_PASSWORD", "changeme")


# ── Auth decorator ─────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            if request.is_json or request.method == "POST":
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


# ── Login page ─────────────────────────────────────────────────
@app.route("/login", methods=["GET"])
def login_page():
    if session.get("authenticated"):
        return redirect(url_for("index"))
    return send_file(LOGIN_PATH)


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400
    if data.get("password") == DEID_PASSWORD:
        session["authenticated"] = True
        session.permanent = True
        return jsonify({"success": True}), 200
    return jsonify({"error": "Incorrect password"}), 401


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True}), 200


# ── Serve the UI ───────────────────────────────────────────────
@app.route("/", methods=["GET"])
@login_required
def index():
    return send_file(UI_PATH)


# ── Health check ───────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "deid-service"}), 200


# ── File upload endpoint (used by the UI) ──────────────────────
@app.route("/deidentify/upload", methods=["POST"])
@login_required
def deidentify_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    uploaded_file = request.files["file"]
    if uploaded_file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    ext = os.path.splitext(uploaded_file.filename)[1].lower()
    if ext not in [".pdf", ".docx"]:
        return jsonify({"error": f"Unsupported file type: {ext}. Use PDF or DOCX."}), 415

    document_id = request.form.get(
        "document_id",
        os.path.splitext(uploaded_file.filename)[0]
    )

    tmp_dir = os.path.join("output_docs", "_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, uploaded_file.filename)
    uploaded_file.save(tmp_path)

    try:
            # Convert PDF to DOCX if needed
            if ext == ".pdf":
                # Redact PDF in-place — preserves all original formatting
                from src.engine.pdf_redactor import redact_pdf
                result = redact_pdf(tmp_path, document_id=document_id)
            else:
                # DOCX — existing in-place redaction
                from src.engine.redactor import redact_docx
                result = redact_docx(tmp_path, document_id=document_id)

            return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

@app.route("/deidentify/download", methods=["GET"])
@login_required
def download_file():
    file_path = request.args.get("path")
    if not file_path:
        return jsonify({"error": "Missing path parameter"}), 400

    # Normalize path — handle backslashes and spaces
    file_path = os.path.normpath(file_path)
    abs_path = os.path.abspath(file_path)

    # Security check — must be inside output_docs
    output_dir = os.path.abspath("output_docs")
    if not abs_path.startswith(output_dir):
        return jsonify({"error": "Invalid file path"}), 403

    if not os.path.exists(abs_path):
        # Log what we looked for to help debug
        app.logger.error(f"File not found: {abs_path}")
        return jsonify({"error": f"File not found: {abs_path}"}), 404

    fname = os.path.basename(abs_path)
    if fname.endswith(".docx"):
        mimetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif fname.endswith(".pdf"):
        mimetype = "application/pdf"
    else:
        mimetype = "application/octet-stream"

    return send_file(abs_path, as_attachment=True, download_name=fname, mimetype=mimetype)

# ── File path endpoint (AnythingLLM skill) ─────────────────────
@app.route("/deidentify", methods=["POST"])
def deidentify():
    data = request.get_json()
    if not data or "file_path" not in data:
        return jsonify({"error": "Missing required field: file_path"}), 400

    file_path = data["file_path"]
    document_id = data.get("document_id", os.path.basename(file_path))
    save_log = data.get("save_log", True)

    if not os.path.exists(file_path):
        return jsonify({"error": f"File not found: {file_path}"}), 404

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in [".pdf", ".docx"]:
        return jsonify({"error": f"Unsupported file type: {ext}"}), 415

    try:
        raw_text = extract_text(file_path)
        result = deidentify_text(raw_text, document_id=document_id)

        output_dir = "output_docs"
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        output_filename = f"REDACTED_{base_name}.txt"
        output_path = os.path.join(output_dir, output_filename)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result["redacted_text"])

        result["output_path"] = output_path

        if save_log:
            log_path = save_redaction_log(result)
            result["log_path"] = log_path

        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Text-only endpoint ─────────────────────────────────────────
@app.route("/deidentify/text", methods=["POST"])
def deidentify_text_only():
    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"error": "Missing required field: text"}), 400
    raw_text = data["text"]
    document_id = data.get("document_id", "text_input")
    try:
        result = deidentify_text(raw_text, document_id=document_id)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)