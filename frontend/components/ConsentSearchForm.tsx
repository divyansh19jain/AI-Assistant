"use client";

interface Props {
  consent: boolean;
  setConsent: (v: boolean) => void;
  firstName: string;
  setFirstName: (v: string) => void;
  lastName: string;
  setLastName: (v: string) => void;
  dob: string;
  setDob: (v: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  loading: boolean;
  error: string | null;
}

export default function ConsentSearchForm({
  consent, setConsent,
  firstName, setFirstName,
  lastName, setLastName,
  dob, setDob,
  onSubmit, loading, error,
}: Props) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <label className="flex items-start gap-3 cursor-pointer bg-amber-50 border border-amber-200 rounded-lg p-3">
        <input
          type="checkbox"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
          className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600"
        />
        <span className="text-sm text-amber-900">
          <strong>I consent</strong> to searching the EMR database for my patient records.
        </span>
      </label>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">First Name</label>
        <input
          type="text" value={firstName} onChange={(e) => setFirstName(e.target.value)}
          required className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
          placeholder="Enter first name"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Last Name</label>
        <input
          type="text" value={lastName} onChange={(e) => setLastName(e.target.value)}
          required className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
          placeholder="Enter last name"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Date of Birth</label>
        <input
          type="date" value={dob} onChange={(e) => setDob(e.target.value)}
          required className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
        />
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-2 text-sm">{error}</div>
      )}

      <button
        type="submit" disabled={loading || !consent}
        className="w-full bg-brand hover:bg-blue-700 disabled:bg-gray-300 text-white font-semibold rounded-lg py-2.5 transition-colors text-sm"
      >
        {loading ? "Searching..." : "Search Records"}
      </button>
    </form>
  );
}
