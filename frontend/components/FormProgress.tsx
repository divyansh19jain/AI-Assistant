interface FormProgressProps {
  answered: number;
  total: number;
  mockMode?: boolean;
}

export default function FormProgress({ answered, total, mockMode }: FormProgressProps) {
  const percent = total > 0 ? Math.round((answered / total) * 100) : 100;
  return (
    <div className="bg-white rounded-xl shadow-sm p-4">
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>Progress</span>
        <span>{answered} of {total} required fields</span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-brand rounded-full transition-all duration-500"
          style={{ width: `${percent}%` }}
        />
      </div>
      {mockMode && (
        <p className="text-xs text-yellow-600 mt-1">MOCK MODE — Using simulated patient data</p>
      )}
    </div>
  );
}
