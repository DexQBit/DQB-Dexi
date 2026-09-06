/**
 * Dexi overdue export → Google Sheets
 *
 * Cron (see wrangler.toml): GET Dexi overdue endpoint, append one row per task.
 * HTTP GET/POST on the Worker URL: same run (manual test without waiting for 1am).
 *
 * Secrets / vars:
 *   DEXI_BASE_URL                  (var)   e.g. https://dexi.dexqbit.com
 *   OVERDUE_EXPORT_SECRET          (secret)
 *   GOOGLE_SHEET_ID                (secret)
 *   GOOGLE_SERVICE_ACCOUNT_EMAIL   (secret)
 *   GOOGLE_PRIVATE_KEY             (secret) PEM from service account JSON
 *   GOOGLE_SHEET_RANGE             (var)   default Sheet1!A:M
 */

const SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets";

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(runExport(env));
  },

  async fetch(request, env, ctx) {
    try {
      const result = await runExport(env);
      return Response.json(result, { status: 200 });
    } catch (err) {
      return Response.json(
        { ok: false, error: err instanceof Error ? err.message : String(err) },
        { status: 500 }
      );
    }
  },
};

async function runExport(env) {
  const baseUrl = (env.DEXI_BASE_URL || "").replace(/\/$/, "");
  const secret = env.OVERDUE_EXPORT_SECRET;
  const sheetId = env.GOOGLE_SHEET_ID;
  const saEmail = env.GOOGLE_SERVICE_ACCOUNT_EMAIL;
  const privateKeyPem = normalizePrivateKey(env.GOOGLE_PRIVATE_KEY);
  const range = env.GOOGLE_SHEET_RANGE || "Sheet1!A:M";

  if (!baseUrl || !secret || !sheetId || !saEmail || !privateKeyPem) {
    throw new Error(
      "Missing required env: DEXI_BASE_URL, OVERDUE_EXPORT_SECRET, GOOGLE_SHEET_ID, GOOGLE_SERVICE_ACCOUNT_EMAIL, GOOGLE_PRIVATE_KEY"
    );
  }

  const dexiRes = await fetch(`${baseUrl}/api/instances/overdue-tasks/export/`, {
    method: "GET",
    headers: {
      Accept: "application/json",
      "X-Overdue-Export-Secret": secret,
    },
  });

  if (!dexiRes.ok) {
    const body = await dexiRes.text();
    throw new Error(`Dexi export failed (${dexiRes.status}): ${body}`);
  }

  const payload = await dexiRes.json();
  const tasks = Array.isArray(payload.tasks) ? payload.tasks : [];
  if (tasks.length === 0) {
    return {
      ok: true,
      overdue_count: 0,
      appended: 0,
      as_of_date: payload.as_of_date,
      message: "No overdue tasks",
    };
  }

  const accessToken = await getGoogleAccessToken(saEmail, privateKeyPem);
  const rows = tasks.map((task) => [
    payload.as_of_date || "",
    payload.generated_at || "",
    task.id || "",
    task.name || "",
    task.sequence_id ?? "",
    task.project_identifier || "",
    task.project_name || "",
    task.workspace_slug || "",
    task.state || "",
    task.priority || "",
    task.target_date || "",
    formatAssignees(task.assignees),
    task.url || "",
  ]);

  const appendUrl = new URL(
    `https://sheets.googleapis.com/v4/spreadsheets/${encodeURIComponent(sheetId)}/values/${encodeURIComponent(range)}:append`
  );
  appendUrl.searchParams.set("valueInputOption", "USER_ENTERED");
  appendUrl.searchParams.set("insertDataOption", "INSERT_ROWS");

  const sheetsRes = await fetch(appendUrl.toString(), {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ values: rows }),
  });

  if (!sheetsRes.ok) {
    const body = await sheetsRes.text();
    throw new Error(`Sheets append failed (${sheetsRes.status}): ${body}`);
  }

  return {
    ok: true,
    overdue_count: payload.overdue_count ?? tasks.length,
    appended: rows.length,
    as_of_date: payload.as_of_date,
  };
}

function formatAssignees(assignees) {
  if (!Array.isArray(assignees) || assignees.length === 0) return "";
  return assignees
    .map((a) => a.display_name || a.email || a.id || "")
    .filter(Boolean)
    .join(", ");
}

function normalizePrivateKey(raw) {
  if (!raw) return "";
  let key = String(raw).trim();
  if (key.includes("\\n")) {
    key = key.replace(/\\n/g, "\n");
  }
  return key;
}

async function getGoogleAccessToken(clientEmail, privateKeyPem) {
  const now = Math.floor(Date.now() / 1000);
  const header = { alg: "RS256", typ: "JWT" };
  const claim = {
    iss: clientEmail,
    scope: SHEETS_SCOPE,
    aud: "https://oauth2.googleapis.com/token",
    iat: now,
    exp: now + 3600,
  };

  const encodedHeader = base64url(JSON.stringify(header));
  const encodedClaim = base64url(JSON.stringify(claim));
  const unsigned = `${encodedHeader}.${encodedClaim}`;
  const signature = await signRs256(unsigned, privateKeyPem);
  const jwt = `${unsigned}.${signature}`;

  const tokenRes = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: jwt,
    }),
  });

  if (!tokenRes.ok) {
    const body = await tokenRes.text();
    throw new Error(`Google token exchange failed (${tokenRes.status}): ${body}`);
  }

  const tokenJson = await tokenRes.json();
  if (!tokenJson.access_token) {
    throw new Error("Google token response missing access_token");
  }
  return tokenJson.access_token;
}

async function signRs256(data, pem) {
  const key = await crypto.subtle.importKey(
    "pkcs8",
    pemToArrayBuffer(pem),
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    key,
    new TextEncoder().encode(data)
  );
  return base64url(sig);
}

function pemToArrayBuffer(pem) {
  const b64 = pem
    .replace(/-----BEGIN PRIVATE KEY-----/g, "")
    .replace(/-----END PRIVATE KEY-----/g, "")
    .replace(/-----BEGIN RSA PRIVATE KEY-----/g, "")
    .replace(/-----END RSA PRIVATE KEY-----/g, "")
    .replace(/\s+/g, "");
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

function base64url(input) {
  let bytes;
  if (typeof input === "string") {
    bytes = new TextEncoder().encode(input);
  } else if (input instanceof ArrayBuffer) {
    bytes = new Uint8Array(input);
  } else {
    bytes = new Uint8Array(input);
  }
  let str = "";
  for (let i = 0; i < bytes.length; i++) {
    str += String.fromCharCode(bytes[i]);
  }
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}
