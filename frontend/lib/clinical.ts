export const CLINICAL_BATTERY_FORM_ID = "BH_SELF_REPORT_BATTERY";
export const MEDICAID_FORM_ID = "ODM_07216";

export interface ClinicalToolOption {
  key: string;
  title: string;
  shortName: string;
  description: string;
  estimate: string;
}

export const clinicalTools: ClinicalToolOption[] = [
  { key: "dsm5_level1", shortName: "DSM-5 Level 1", title: "DSM-5-TR Level 1 Cross-Cutting", description: "Broad symptom check across mood, anxiety, sleep, substance use, and safety domains.", estimate: "8-10 min" },
  { key: "phq9", shortName: "PHQ-9", title: "PHQ-9", description: "Depression symptom screen for the last two weeks.", estimate: "2-3 min" },
  { key: "gad7", shortName: "GAD-7", title: "GAD-7", description: "Anxiety symptom screen for the last two weeks.", estimate: "2-3 min" },
  { key: "cssrs", shortName: "C-SSRS", title: "C-SSRS Self-Report", description: "Direct suicide safety self-report screener.", estimate: "2-3 min" },
  { key: "auditc", shortName: "AUDIT-C", title: "AUDIT-C", description: "Brief alcohol-use screen.", estimate: "1-2 min" },
  { key: "taps", shortName: "TAPS", title: "TAPS", description: "Tobacco, alcohol, prescription medication, and substance-use screen.", estimate: "2-3 min" },
  { key: "dast10", shortName: "DAST-10", title: "DAST-10", description: "Drug-use related problem screen.", estimate: "3-4 min" },
  { key: "pcl5", shortName: "PCL-5", title: "PCL-5", description: "PTSD symptom screen when trauma history is relevant.", estimate: "5-7 min" },
  { key: "mdq", shortName: "MDQ", title: "Mood Disorder Questionnaire", description: "Mood elevation, energy, and bipolar-spectrum screening pattern.", estimate: "4-5 min" },
  { key: "whodas12", shortName: "WHODAS", title: "WHODAS 2.0", description: "Functioning and disability screen for the last 30 days.", estimate: "4-5 min" },
  { key: "dla20", shortName: "DLA-20", title: "DLA-20 Self-Report", description: "Daily-living functioning self-report domains.", estimate: "6-8 min" },
];

export function selectedToolGateAnswers(selectedKeys: string[]): Record<string, boolean> {
  const selected = new Set(selectedKeys);
  return Object.fromEntries(
    clinicalTools.map((tool) => [`selected.${tool.key}`, selected.has(tool.key)])
  );
}

export function estimatedClinicalMinutes(selectedKeys: string[]): string {
  const count = selectedKeys.length;
  if (count <= 1) return "about 5 to 10 minutes";
  if (count <= 3) return "about 10 to 20 minutes";
  if (count <= 6) return "about 20 to 35 minutes";
  return "about 35 to 60 minutes";
}
