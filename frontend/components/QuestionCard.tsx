import type { NextQuestion } from "@/lib/types";

interface Props {
  question: NextQuestion;
  answer: string;
  onAnswerChange: (v: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  onSkip?: () => void;
  submitting: boolean;
  clarification?: string | null;
  error?: string | null;
}

export default function QuestionCard({
  question: q,
  answer,
  onAnswerChange,
  onSubmit,
  onSkip,
  submitting,
  clarification,
  error,
}: Props) {
  return (
    <div className="bg-white rounded-2xl shadow-md p-6">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
          {q.field.section.replace(/_/g, " ")}
        </span>
        {q.is_sensitive && (
          <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full">Sensitive</span>
        )}
        {q.is_optional && (
          <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">Optional</span>
        )}
      </div>

      <p className="text-base font-semibold text-gray-800 mt-2 mb-1">{q.field.label}</p>

      {clarification ? (
        <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-3">
          {clarification}
        </p>
      ) : (
        <p className="text-sm text-gray-500 mb-3">{q.question}</p>
      )}

      <form onSubmit={onSubmit} className="space-y-3">
        {q.field_type === "boolean" ? (
          <div className="flex gap-3">
            {["Yes", "No"].map((opt) => (
              <button
                key={opt}
                type="button"
                onClick={() => onAnswerChange(opt.toLowerCase())}
                className={`flex-1 rounded-lg border py-2 text-sm font-medium transition-colors ${
                  answer === opt.toLowerCase()
                    ? "border-blue-500 bg-blue-50 text-blue-700"
                    : "border-gray-300 text-gray-600 hover:bg-gray-50"
                }`}
              >
                {opt}
              </button>
            ))}
          </div>
        ) : (
          <input
            type={q.field_type === "date" ? "date" : q.is_sensitive ? "password" : "text"}
            value={answer}
            onChange={(e) => onAnswerChange(e.target.value)}
            placeholder={`Enter ${q.field.label.toLowerCase()}`}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            autoFocus
          />
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={submitting || !answer.trim()}
            className="flex-1 bg-brand text-white font-semibold rounded-lg py-2.5 text-sm hover:bg-blue-700 disabled:bg-gray-300 transition-colors"
          >
            {submitting ? "Saving..." : "Save Answer"}
          </button>
          {q.is_optional && onSkip && (
            <button
              type="button"
              onClick={onSkip}
              disabled={submitting}
              className="px-4 border border-gray-300 text-gray-600 rounded-lg text-sm hover:bg-gray-50"
            >
              Skip
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
