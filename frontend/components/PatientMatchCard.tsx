import type { MaskedPatient } from "@/lib/types";

interface Props {
  patient: MaskedPatient;
  selected: boolean;
  onSelect: () => void;
}

export default function PatientMatchCard({ patient, selected, onSelect }: Props) {
  return (
    <button
      onClick={onSelect}
      className={`w-full text-left border rounded-xl p-4 transition-all ${
        selected
          ? "border-blue-500 bg-blue-50 ring-2 ring-blue-400"
          : "border-gray-200 hover:border-blue-300 hover:bg-gray-50"
      }`}
    >
      {/* Values are masked at the backend EMR boundary (app/emr/masking.py), e.g.
          "T***", "****-**-15", "***-***-1234" — enough for the user to recognize their
          own record without exposing full PHI. */}
      <div className="flex items-center gap-2 mb-1">
        <div className="h-8 w-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-700 font-bold text-sm">
          {patient.first_name?.[0] ?? "?"}
        </div>
        <div>
          <p className="font-semibold text-gray-800 text-sm">
            {patient.first_name} {patient.last_name}
          </p>
          <p className="text-xs text-gray-500">DOB: {patient.dob}</p>
        </div>
        {patient.is_mock && (
          <span className="ml-auto text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">
            mock
          </span>
        )}
      </div>
      {patient.phone && (
        <p className="text-xs text-gray-400 ml-10">Phone: {patient.phone}</p>
      )}
    </button>
  );
}
