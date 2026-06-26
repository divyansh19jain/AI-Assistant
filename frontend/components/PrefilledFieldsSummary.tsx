import type { SessionFieldSummary } from "@/lib/types";

interface Props {
  fields: SessionFieldSummary[];
}

export default function PrefilledFieldsSummary({ fields }: Props) {
  if (fields.length === 0) return null;
  return (
    <div className="bg-green-50 border border-green-200 rounded-xl p-4">
      <p className="text-sm font-medium text-green-800 mb-2">
        {fields.length} field{fields.length !== 1 ? "s" : ""} pre-filled from EMR
      </p>
      <div className="grid grid-cols-2 gap-1">
        {fields.slice(0, 8).map((f) => (
          <div key={f.field_key} className="text-xs text-green-700 truncate">
            {f.label}: {f.is_sensitive ? "***" : String(f.value ?? "")}
          </div>
        ))}
        {fields.length > 8 && (
          <p className="text-xs text-green-600 col-span-2">...and {fields.length - 8} more</p>
        )}
      </div>
    </div>
  );
}
