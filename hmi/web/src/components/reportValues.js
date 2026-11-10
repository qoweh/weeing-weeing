const fields = [
  "department", "processImpact", "actualActions", "actionStatus", "replacedParts", "actionAt",
  "causeCategory", "confirmedCause", "causeEvidence", "aiAssessment", "trialResult",
  "trialDetails", "downtimeStart", "downtimeEnd", "resolution", "followUp",
  "followUpOwner", "followUpDue", "beforePhoto", "afterPhoto", "beforeCaption", "afterCaption", "beforeTakenAt", "afterTakenAt", "beforeLocation", "afterLocation",
];
const dates = new Set(["actionAt", "downtimeStart", "downtimeEnd", "beforeTakenAt", "afterTakenAt"]);
const snake = (name) => name.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);

function localTime(value) {
  if (!value) return "";
  const time = new Date(value);
  const adjusted = new Date(time.getTime() - time.getTimezoneOffset() * 60_000);
  return adjusted.toISOString().slice(0, 16);
}

export function formValues(document) {
  if (!document) return {};
  return Object.fromEntries(fields.map((name) => {
    const value = document.form_data[snake(name)];
    return [name, dates.has(name) ? localTime(value) : value ?? ""];
  }));
}

export function draftValues(values) {
  return Object.fromEntries(fields.map((name) => {
    let value = values[name] ?? "";
    if (dates.has(name)) value = value ? new Date(value).toISOString() : null;
    return [snake(name), value];
  }));
}
