from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import os
import subprocess
import shutil
import sys
import re


# ==================================================
# APP CONFIGURATION
# ==================================================

app = FastAPI(
    title="AudioSplitAI",
    description="AI-powered music source separation and mixing API",
    version="1.0.0",
)


# ==================================================
# STATIC FILES
# ==================================================

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)


# ==================================================
# CORS
# ==================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================================================
# DIRECTORIES
# ==================================================

INPUT_DIR = "uploads"
OUTPUT_DIR = "separated"

os.makedirs(
    INPUT_DIR,
    exist_ok=True
)

os.makedirs(
    OUTPUT_DIR,
    exist_ok=True
)


# ==================================================
# HELPER
# ==================================================

def safe_filename(filename: str) -> str:
    """
    Make uploaded filenames safe.
    """

    filename = os.path.basename(
        filename
    )

    filename = re.sub(
        r"[^a-zA-Z0-9._ -]",
        "_",
        filename
    )

    return filename


# ==================================================
# HOME
# ==================================================

@app.get("/")
def home():

    return FileResponse(
        "static/index.html"
    )


# ==================================================
# HEALTH CHECK
# ==================================================

@app.get("/health")
def health():

    return {
        "status": "ok",
        "service": "AudioSplitAI",
        "version": "1.0.0"
    }


# ==================================================
# AUDIO SEPARATION
# ==================================================

@app.post("/separate")
async def separate(
    file: UploadFile = File(...)
):

    # ------------------------------------------------
    # CHECK FILE
    # ------------------------------------------------

    if not file.filename:

        raise HTTPException(
            status_code=400,
            detail="No audio file selected."
        )


    # ------------------------------------------------
    # ALLOWED AUDIO FORMATS
    # ------------------------------------------------

    allowed_extensions = {
        ".mp3",
        ".wav",
        ".m4a",
        ".flac",
        ".ogg",
        ".aac"
    }


    extension = os.path.splitext(
        file.filename
    )[1].lower()


    if extension not in allowed_extensions:

        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported audio format. "
                "Please upload MP3, WAV, M4A, "
                "FLAC, OGG or AAC."
            )
        )


    # ------------------------------------------------
    # SAFE FILENAME
    # ------------------------------------------------

    filename = safe_filename(
        file.filename
    )


    input_path = os.path.join(
        INPUT_DIR,
        filename
    )


    # ------------------------------------------------
    # SONG NAME
    # ------------------------------------------------

    song_name = os.path.splitext(
        filename
    )[0]


    # ------------------------------------------------
    # OUTPUT FOLDER
    # ------------------------------------------------

    output_folder = os.path.join(
        OUTPUT_DIR,
        "htdemucs",
        song_name
    )


    # ------------------------------------------------
    # REQUIRED STEMS
    # ------------------------------------------------

    required_stems = [
        "vocals.wav",
        "drums.wav",
        "bass.wav",
        "other.wav"
    ]


    # =================================================
    # CACHE CHECK
    # =================================================

    stems_already_exist = all(
        os.path.exists(
            os.path.join(
                output_folder,
                stem
            )
        )
        for stem in required_stems
    )


    if stems_already_exist:

        return {
            "filename": filename,
            "message": "Existing separation loaded.",
            "cached": True,
            "stems": [
                "vocals",
                "drums",
                "bass",
                "other"
            ],
            "output_folder": output_folder
        }


    # =================================================
    # SAVE UPLOADED FILE
    # =================================================

    try:

        with open(
            input_path,
            "wb"
        ) as buffer:

            shutil.copyfileobj(
                file.file,
                buffer
            )

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=(
                f"Could not save uploaded "
                f"audio file: {error}"
            )
        )


    # =================================================
    # DEMUCS COMMAND
    # =================================================

    command = [
        sys.executable,

        "-m",
        "demucs",

        # AI model
        "-n",
        "htdemucs",

        # Output directory
        "-o",
        OUTPUT_DIR,

        # Faster processing
        "--shifts",
        "0",

        # Lower overlap for faster processing
        "--overlap",
        "0.10",

        # Segment size
        "--segment",
        "7",

        # CPU workers
        "-j",
        "2",

        # Input audio
        input_path
    ]


    # =================================================
    # RUN DEMUCS
    # =================================================

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=1800
        )

    except subprocess.TimeoutExpired:

        raise HTTPException(
            status_code=504,
            detail=(
                "Audio separation took too long. "
                "Try a shorter audio file."
            )
        )

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=(
                f"Could not start Demucs: {error}"
            )
        )


    # =================================================
    # CHECK DEMUCS RESULT
    # =================================================

    if result.returncode != 0:

        error_message = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Unknown Demucs error."
        )


        raise HTTPException(
            status_code=500,
            detail=error_message
        )


    # =================================================
    # VERIFY OUTPUT
    # =================================================

    missing_stems = []


    for stem in required_stems:

        stem_path = os.path.join(
            output_folder,
            stem
        )


        if not os.path.exists(
            stem_path
        ):

            missing_stems.append(
                stem
            )


    if missing_stems:

        raise HTTPException(
            status_code=500,
            detail=(
                "Audio separation finished, "
                "but these stems are missing: "
                + ", ".join(
                    missing_stems
                )
            )
        )


    # =================================================
    # SUCCESS
    # =================================================

    return {

        "filename": filename,

        "message":
            "Audio separated successfully.",

        "cached":
            False,

        "stems": [
            "vocals",
            "drums",
            "bass",
            "other"
        ],

        "output_folder":
            output_folder
    }


# ==================================================
# DOWNLOAD STEM
# ==================================================

@app.get(
    "/download/{song_name}/{stem}"
)
async def download_stem(
    song_name: str,
    stem: str
):

    # ------------------------------------------------
    # ALLOWED STEMS
    # ------------------------------------------------

    allowed_stems = {
        "vocals",
        "drums",
        "bass",
        "other"
    }


    if stem not in allowed_stems:

        raise HTTPException(
            status_code=400,
            detail="Invalid stem requested."
        )


    # ------------------------------------------------
    # SAFE SONG NAME
    # ------------------------------------------------

    song_name = safe_filename(
        song_name
    )


    # ------------------------------------------------
    # FILE PATH
    # ------------------------------------------------

    file_path = os.path.join(
        OUTPUT_DIR,
        "htdemucs",
        song_name,
        f"{stem}.wav"
    )


    # ------------------------------------------------
    # SECURITY CHECK
    # ------------------------------------------------

    base_directory = os.path.abspath(
        os.path.join(
            OUTPUT_DIR,
            "htdemucs"
        )
    )


    absolute_file_path = os.path.abspath(
        file_path
    )


    if not absolute_file_path.startswith(
        base_directory + os.sep
    ):

        raise HTTPException(
            status_code=403,
            detail="Invalid file path."
        )


    # ------------------------------------------------
    # CHECK FILE
    # ------------------------------------------------

    if not os.path.exists(
        file_path
    ):

        raise HTTPException(
            status_code=404,
            detail=(
                f"{stem.capitalize()} "
                "stem was not found."
            )
        )


    # ------------------------------------------------
    # SEND AUDIO
    # ------------------------------------------------

    return FileResponse(

        file_path,

        media_type="audio/wav",

        filename=(
            f"{song_name}_{stem}.wav"
        )
    )