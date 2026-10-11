import { useState } from "react";
import { submitFeedback, type FeedbackSubmission } from "../api";

export default function FeedbackModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const [rating, setRating] = useState<number>(5);
  const [name, setName] = useState("");
  const [role, setRole] = useState<FeedbackSubmission["role"]>("Student");
  const [workedAsExpected, setWorkedAsExpected] = useState<"yes" | "partially" | "no">("yes");
  const [liked, setLiked] = useState("");
  const [confusing, setConfusing] = useState("");
  const [featureToImprove, setFeatureToImprove] = useState("");
  const [bugs, setBugs] = useState("");
  const [suggestions, setSuggestions] = useState("");
  const [consentToPublish, setConsentToPublish] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);

  if (!isOpen) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await submitFeedback({
        rating,
        name: name.trim() || undefined,
        role,
        worked_as_expected: workedAsExpected,
        liked: liked.trim(),
        confusing: confusing.trim(),
        feature_to_improve: featureToImprove.trim(),
        bugs: bugs.trim(),
        suggestions: suggestions.trim(),
        consent_to_publish: consentToPublish,
      });
      setSubmitted(true);
    } catch (err) {
      setError((err as Error).message || "Failed to submit feedback. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  function handleReset() {
    setSubmitted(false);
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="feedback-modal-title"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="relative max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-3xl border border-[#2a3352] bg-[#12172a] p-6 shadow-2xl text-ink">
        <button
          onClick={onClose}
          disabled={submitting}
          aria-label="Close feedback modal"
          className="absolute right-5 top-5 rounded-full p-2 text-muted hover:bg-[#1a223c] hover:text-white transition"
        >
          <svg className="h-5 w-5" viewBox="0 0 24 24" stroke="currentColor" fill="none">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        {submitted ? (
          <div className="py-10 text-center">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-[#1b3d32] text-[#34d399]">
              <svg className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="font-display text-2xl font-extrabold text-white">Thank You for Your Feedback!</h2>
            <p className="mt-2 text-sm text-muted max-w-md mx-auto">
              Your honest evaluation helps us improve SATYAM AI's explainability, reliability, and accuracy under Challenge Card 2.
            </p>
            <button
              onClick={handleReset}
              className="mt-6 rounded-xl bg-violet px-6 py-2.5 text-sm font-bold text-white hover:brightness-110 transition"
            >
              Close
            </button>
          </div>
        ) : (
          <div>
            <div className="mb-6">
              <span className="text-xs font-bold uppercase tracking-wider text-violet">Evaluation & Feedback</span>
              <h2 id="feedback-modal-title" className="mt-1 font-display text-2xl font-extrabold text-white">
                Share Your Experience with SATYAM AI
              </h2>
              <p className="mt-1 text-xs text-muted">
                Help us evaluate SATYAM AI for Challenge Card 2. Your feedback informs forensic usability, explainability, and technical improvements.
              </p>
            </div>

            {error && (
              <div role="alert" className="mb-4 rounded-xl bg-[#ffe4df] p-3 text-xs font-bold text-[#7a1b0c]">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4 text-xs">
              {/* Star Rating */}
              <div>
                <label className="block font-bold text-ink mb-1.5">
                  Overall experience rating <span className="text-violet">*</span>
                </label>
                <div className="flex items-center gap-2" role="radiogroup" aria-label="Experience rating 1 to 5">
                  {[1, 2, 3, 4, 5].map((star) => (
                    <button
                      key={star}
                      type="button"
                      onClick={() => setRating(star)}
                      className={`flex h-10 w-12 items-center justify-center rounded-xl border text-sm font-bold transition ${
                        rating >= star
                          ? "border-violet bg-violet text-white shadow-lg shadow-violet/20"
                          : "border-[#2a3352] bg-[#171f38] text-muted hover:border-[#3d4a75]"
                      }`}
                      aria-label={`${star} star${star > 1 ? "s" : ""}`}
                    >
                      ★ {star}
                    </button>
                  ))}
                  <span className="ml-2 text-xs text-muted">
                    {rating === 5 ? "Excellent" : rating === 4 ? "Very Good" : rating === 3 ? "Adequate" : rating === 2 ? "Needs Work" : "Unsatisfactory"}
                  </span>
                </div>
              </div>

              {/* Role & Name */}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="block font-bold text-ink mb-1">Your role (optional)</label>
                  <select
                    value={role}
                    onChange={(e) => setRole(e.target.value as FeedbackSubmission["role"])}
                    className="w-full rounded-xl border border-[#2a3352] bg-[#171f38] p-2.5 text-xs text-ink focus:border-violet focus:outline-none"
                  >
                    <option value="Student">Student</option>
                    <option value="Developer">Developer / Engineer</option>
                    <option value="Researcher">Researcher / Academic</option>
                    <option value="Journalist">Journalist / Fact-checker</option>
                    <option value="Other">Other</option>
                  </select>
                </div>
                <div>
                  <label className="block font-bold text-ink mb-1">Name or nickname (optional)</label>
                  <input
                    type="text"
                    maxLength={100}
                    placeholder="e.g. Alex"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="w-full rounded-xl border border-[#2a3352] bg-[#171f38] p-2.5 text-xs text-ink placeholder-muted/60 focus:border-violet focus:outline-none"
                  />
                </div>
              </div>

              {/* Did it work as expected */}
              <div>
                <label className="block font-bold text-ink mb-1">Did the application work as expected?</label>
                <div className="flex gap-2">
                  {(["yes", "partially", "no"] as const).map((opt) => (
                    <button
                      key={opt}
                      type="button"
                      onClick={() => setWorkedAsExpected(opt)}
                      className={`flex-1 rounded-xl border p-2 text-center font-bold capitalize transition ${
                        workedAsExpected === opt
                          ? "border-violet bg-violet/20 text-white"
                          : "border-[#2a3352] bg-[#171f38] text-muted hover:border-[#3d4a75]"
                      }`}
                    >
                      {opt === "yes" ? "✓ Yes" : opt === "partially" ? "◐ Partially" : "✕ No"}
                    </button>
                  ))}
                </div>
              </div>

              {/* What did you like */}
              <div>
                <label className="block font-bold text-ink mb-1">What did you like about SATYAM AI?</label>
                <textarea
                  rows={2}
                  maxLength={2000}
                  placeholder="e.g. Transparent uncertainty reporting, separate audio/video checks, no fake certainty..."
                  value={liked}
                  onChange={(e) => setLiked(e.target.value)}
                  className="w-full rounded-xl border border-[#2a3352] bg-[#171f38] p-2.5 text-xs text-ink placeholder-muted/60 focus:border-violet focus:outline-none"
                />
              </div>

              {/* What was confusing */}
              <div>
                <label className="block font-bold text-ink mb-1">What was confusing, difficult, or unexpected?</label>
                <textarea
                  rows={2}
                  maxLength={2000}
                  placeholder="e.g. Score semantics explanation, difference between raw score and probability..."
                  value={confusing}
                  onChange={(e) => setConfusing(e.target.value)}
                  className="w-full rounded-xl border border-[#2a3352] bg-[#171f38] p-2.5 text-xs text-ink placeholder-muted/60 focus:border-violet focus:outline-none"
                />
              </div>

              {/* Feature to improve & bugs */}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="block font-bold text-ink mb-1">Which feature should be improved first?</label>
                  <input
                    type="text"
                    maxLength={500}
                    placeholder="e.g. Batch analysis, more audio codecs..."
                    value={featureToImprove}
                    onChange={(e) => setFeatureToImprove(e.target.value)}
                    className="w-full rounded-xl border border-[#2a3352] bg-[#171f38] p-2.5 text-xs text-ink placeholder-muted/60 focus:border-violet focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block font-bold text-ink mb-1">Any bugs or errors encountered?</label>
                  <input
                    type="text"
                    maxLength={500}
                    placeholder="e.g. Timeout on 4K MP4 video, etc."
                    value={bugs}
                    onChange={(e) => setBugs(e.target.value)}
                    className="w-full rounded-xl border border-[#2a3352] bg-[#171f38] p-2.5 text-xs text-ink placeholder-muted/60 focus:border-violet focus:outline-none"
                  />
                </div>
              </div>

              {/* General suggestions */}
              <div>
                <label className="block font-bold text-ink mb-1">Additional suggestions or thoughts (optional)</label>
                <textarea
                  rows={2}
                  maxLength={2000}
                  placeholder="Suggestions for future evaluation milestones..."
                  value={suggestions}
                  onChange={(e) => setSuggestions(e.target.value)}
                  className="w-full rounded-xl border border-[#2a3352] bg-[#171f38] p-2.5 text-xs text-ink placeholder-muted/60 focus:border-violet focus:outline-none"
                />
              </div>

              {/* Privacy Consent */}
              <div className="rounded-xl border border-[#2a3352] bg-[#171f38] p-3 text-muted">
                <label className="flex items-start gap-2.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={consentToPublish}
                    onChange={(e) => setConsentToPublish(e.target.checked)}
                    className="mt-0.5 h-4 w-4 rounded border-[#2a3352] bg-[#111625] text-violet accent-violet focus:ring-0"
                  />
                  <span className="text-[11px] leading-relaxed">
                    I consent to having this feedback quoted anonymously in SATYAM AI's project evaluation report. No media files or personal passwords are ever shared.
                  </span>
                </label>
              </div>

              {/* Actions */}
              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={submitting}
                  className="rounded-xl border border-[#2a3352] px-4 py-2.5 text-xs font-bold text-muted hover:bg-[#1a223c] hover:text-white transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="rounded-xl bg-violet px-6 py-2.5 text-xs font-bold text-white shadow-lg shadow-violet/20 hover:brightness-110 disabled:opacity-50 transition"
                >
                  {submitting ? "Submitting…" : "Submit Feedback"}
                </button>
              </div>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
