let accessToken = "";

export function setAccessToken(token) {
  accessToken = token;
}

export async function request(
  path,
  { method = "GET", body, signal, responseType = "json" } = {},
) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 300_000);
  const isFormData = body instanceof FormData;
  const cancel = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });

  try {
    const response = await fetch(`/api${path}`, {
      method,
      cache: "no-store",
      signal: controller.signal,
      headers: {
        ...(body !== undefined && !isFormData
          ? { "Content-Type": "application/json" }
          : {}),
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: body === undefined || isFormData ? body : JSON.stringify(body),
    });

    if (response.ok && responseType === "blob") return await response.blob();
    const text = await response.text();
    let data;

    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      throw new Error(
        `서버가 JSON 형식으로 응답하지 않았습니다. HTTP ${response.status}`,
      );
    }

    if (!response.ok) {
      const detail = data?.detail ?? data?.message ?? "요청 실패";
      const message =
        typeof detail === "string"
          ? detail
          : (detail?.message ?? JSON.stringify(detail));

      const error = new Error(`HTTP ${response.status}: ${message}`);
      error.status = response.status;
      error.detail = detail;
      error.data = data;
      throw error;
    }

    return data;
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error.name === "AbortError") {
      throw new Error(
        "응답 대기 시간이 초과됐습니다. 서버에서 처리가 계속되는지 확인하세요.",
        { cause: error },
      );
    }

    if (error instanceof TypeError) {
      throw new Error(
        "서버에 연결하지 못했습니다. FastAPI 실행 상태를 확인하세요.",
        { cause: error },
      );
    }

    throw error;
  } finally {
    signal?.removeEventListener("abort", cancel);
    clearTimeout(timer);
  }
}

export function checkHealth() {
  return request("/health");
}

export async function uploadDocument(formData, onProgress = () => {}) {
  onProgress("uploading");

  let job = await request("/documents", {
    method: "POST",
    body: formData,
  });

  const uploadId = job.upload_id;
  if (!uploadId) {
    throw new Error("서버 응답에 업로드 ID가 없습니다.");
  }

  const deadline = Date.now() + 30 * 60 * 1000;

  while (true) {
    onProgress(job.stage ?? job.status);

    if (job.status === "completed") {
      return job;
    }

    if (job.status === "failed") {
      throw new Error(
        `${job.error ?? "문서 처리에 실패했습니다."} 업로드 ID: ${uploadId}`,
      );
    }

    if (!["queued", "processing"].includes(job.status)) {
      throw new Error(`알 수 없는 처리 상태입니다: ${job.status}`);
    }

    if (Date.now() >= deadline) {
      throw new Error(
        `처리 상태 확인 시간이 초과됐습니다. 서버 작업은 계속될 수 있습니다. 업로드 ID: ${uploadId}`,
      );
    }

    await new Promise((resolve) => setTimeout(resolve, 500));

    try {
      job = await request(`/documents/${encodeURIComponent(uploadId)}`);
    } catch (error) {
      throw new Error(
        `상태 조회에 실패했습니다. 서버 작업은 계속될 수 있습니다. 업로드 ID: ${uploadId}. ${error.message}`,
        { cause: error },
      );
    }
  }
}

export function loginUser(employeeNo, password) {
  return request("/auth/login", {
    method: "POST",
    body: { employee_no: employeeNo, password },
  });
}

export function currentUser() {
  return request("/auth/me");
}
export function logoutUser() {
  return request("/auth/logout", { method: "POST" });
}
export function listIncidents() {
  return request("/incidents");
}
export function getIncidentAnalysis(id) {
  return request(`/incidents/${encodeURIComponent(id)}/analysis`);
}
export function listReports(scope = "mine") {
  return request(`/reports?scope=${encodeURIComponent(scope)}`);
}
export function getReport(id, version, signal) {
  const suffix = version ? `/versions/${version}` : "";
  return request(`/reports/${encodeURIComponent(id)}${suffix}`, { signal });
}
export function saveReport(id, body) {
  return request(id ? `/reports/${encodeURIComponent(id)}/draft` : "/reports", {
    method: id ? "PUT" : "POST",
    body,
  });
}
export function actOnReport(id, action, revision, comment = "") {
  return request(
    `/reports/${encodeURIComponent(id)}/${encodeURIComponent(action)}`,
    {
      method: "POST",
      body: { expected_revision: revision, comment },
    },
  );
}

export function listDocuments(query = "") {
  const params = new URLSearchParams({ q: query });
  return request(query ? `/documents?${params}` : "/documents");
}

export function deleteDocument(document) {
  return request(`/documents/${encodeURIComponent(document.doc_id)}`, {
    method: "DELETE",
    body: {
      doc_version: document.doc_version,
      source_sha256: document.source_sha256,
      upload_id: document.upload_id,
    },
  });
}

export async function fetchDocumentFile(uploadId) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60_000);

  try {
    const response = await fetch(
      `/api/documents/${encodeURIComponent(uploadId)}/file`,
      {
        cache: "no-store",
        signal: controller.signal,
        headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
      },
    );

    if (!response.ok) {
      const error = new Error(
        [404, 405].includes(response.status)
          ? "서버에서 문서 원문(PDF)을 찾을 수 없습니다."
          : `문서 원문을 불러오지 못했습니다. HTTP ${response.status}`,
      );
      error.status = response.status;
      throw error;
    }

    return await response.blob();
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("문서 원문 응답 대기 시간이 초과됐습니다.", {
        cause: error,
      });
    }
    if (error instanceof TypeError) {
      throw new Error(
        "서버에 연결하지 못했습니다. FastAPI 실행 상태를 확인하세요.",
        { cause: error },
      );
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
