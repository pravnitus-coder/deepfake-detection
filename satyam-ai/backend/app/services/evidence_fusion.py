"""Transparent rule-based fusion. It does NOT average scores and never outputs a calibrated probability."""

RULES = ("(1) Modules supporting both sides => inconclusive (conflict shown). "
         "(2) A configured model flags + at least 2 modules support manipulation => likely manipulated, HIGH. "
         "(3) A configured model flags alone => likely manipulated, MODERATE. "
         "(4) Only non-model evidence: 2+ signals => MODERATE, one signal => inconclusive. "
         "(5) 'No strong evidence' requires a completed AI model that does not flag the media; metadata alone never clears media.")


def fuse(modules: list) -> dict:
    model_ids = {"ai_model", "audio_model", "video_frames", "video_audio"}
    by = {"supports_manipulation": [], "supports_authenticity": [], "inconclusive": []}
    unavailable = []
    for m in modules:
        if m["status"] != "completed":
            unavailable.append({"id": m["id"], "status": m["status"], "reason": m["summary"]})
        elif m["stance"] in by:
            by[m["stance"]].append(m["id"])
    man, auth = by["supports_manipulation"], by["supports_authenticity"]
    conflicts = []
    if man and auth:
        conflicts.append({"supports_manipulation": man, "supports_authenticity": auth,
                          "note": "Modules disagree. Both sets of findings are shown; none is hidden."})
        assessment, risk = "inconclusive", "MODERATE"
    elif model_ids.intersection(man):
        assessment, risk = "likely_manipulated", "HIGH" if len(man) >= 2 else "MODERATE"
    elif man:
        assessment, risk = ("likely_manipulated", "MODERATE") if len(man) >= 2 else ("inconclusive", "MODERATE")
    elif model_ids.intersection(auth):
        assessment, risk = "no_strong_evidence", "LOW"
    else:
        assessment, risk = "inconclusive", "UNDETERMINED"
    texts = {"likely_manipulated": "Some checks suggest this media may be AI-generated or manipulated.",
             "no_strong_evidence": "The available checks did not find strong evidence of manipulation. This does not prove the media is authentic.",
             "inconclusive": "The available evidence is not enough to lean either way."}
    return {"assessment": assessment, "risk_indicator": risk, "calibrated_probability": None,
            "calibration_note": "No calibrated probability is shown: the fusion rules have not been validated or calibrated on labelled data. The risk indicator is a heuristic.",
            "method": "SATYAM Evidence Fusion Engine (rule-based heuristic)", "rules": RULES,
            "explanation": texts[assessment], "agreement": by, "conflicts": conflicts, "unavailable": unavailable}
