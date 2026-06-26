interface Props {
  missingKeys: string[];
  onGoBack: () => void;
}

export default function MissingFieldsList({ missingKeys, onGoBack }: Props) {
  if (missingKeys.length === 0) return null;
  return (
    <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-xl px-4 py-3 text-sm">
      <strong>{missingKeys.length} required field(s) missing:</strong>{" "}
      {missingKeys.slice(0, 5).join(", ")}
      {missingKeys.length > 5 && " ...and more"}
      <br />
      <button onClick={onGoBack} className="text-amber-700 underline mt-1 text-xs">
        Go back to complete them
      </button>
    </div>
  );
}
