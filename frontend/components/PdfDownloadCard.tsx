import type { GeneratePdfResponse } from "@/lib/types";
import { api } from "@/lib/api";

interface Props {
  sessionId: string;
  result: GeneratePdfResponse;
  onRegenerate: () => void;
  generating: boolean;
}

export default function PdfDownloadCard({ sessionId, result, onRegenerate, generating }: Props) {
  return (
    <div className="space-y-3">
      <div
        className={`rounded-lg px-4 py-3 text-sm ${
          result.is_fallback
            ? "bg-yellow-50 border border-yellow-200 text-yellow-800"
            : "bg-green-50 border border-green-200 text-green-700"
        }`}
      >
        {result.is_fallback
          ? "PDF generated as data summary (fallback). Place ODM07216fillx.pdf in backend/app/pdf/ to enable field-filled output."
          : "PDF generated with filled form fields."}
      </div>
      <a
        href={api.downloadPdfUrl(sessionId)}
        download={result.file_name}
        className="block w-full text-center bg-green-600 hover:bg-green-700 text-white font-semibold rounded-lg py-2.5 text-sm"
      >
        Download PDF — {result.file_name}
      </a>
      <button
        onClick={onRegenerate}
        disabled={generating}
        className="w-full border border-gray-300 text-gray-600 rounded-lg py-2 text-sm hover:bg-gray-50"
      >
        {generating ? "Re-generating..." : "Re-generate PDF"}
      </button>
    </div>
  );
}
