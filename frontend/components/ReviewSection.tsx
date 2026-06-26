import type { ReviewField } from "@/lib/types";

const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
  emr: { label: "EMR", color: "bg-green-100 text-green-700" },
  user: { label: "User", color: "bg-blue-100 text-blue-700" },
  voice: { label: "AI Voice", color: "bg-purple-100 text-purple-700" },
  missing: { label: "Missing", color: "bg-red-100 text-red-600" },
};

interface Props {
  sectionTitle: string;
  fields: ReviewField[];
}

export default function ReviewSection({ sectionTitle, fields }: Props) {
  const visibleFields = fields.filter(
    (f) => f.value !== null && f.value !== undefined || f.is_required
  );
  if (visibleFields.length === 0) return null;

  return (
    <div className="bg-white rounded-xl shadow-sm overflow-hidden">
      <div className="bg-gray-50 border-b px-5 py-3">
        <h3 className="text-sm font-semibold text-gray-700">{sectionTitle}</h3>
      </div>
      <div className="divide-y">
        {visibleFields.map((field) => {
          const src = SOURCE_LABELS[field.source] || SOURCE_LABELS.missing;
          const isMissing = field.value === null || field.value === undefined;
          return (
            <div
              key={field.field_key}
              className={`flex items-start px-5 py-3 ${isMissing && field.is_required ? "bg-red-50" : ""}`}
            >
              <div className="flex-1 min-w-0">
                <p className="text-xs text-gray-500">{field.label}</p>
                <p className={`text-sm font-medium ${isMissing ? "text-red-500 italic" : "text-gray-800"}`}>
                  {isMissing ? "Not provided" : field.is_sensitive ? "***" : String(field.value)}
                </p>
              </div>
              <span className={`ml-3 mt-0.5 text-xs px-2 py-0.5 rounded-full flex-shrink-0 ${src.color}`}>
                {src.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
