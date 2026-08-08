// Reads the local capture queue the Python engine writes to (engine/contribute.py)
// and handles the two actions a human can take on each item: approve (upload
// it, then delete the local copy) or reject (just delete it). The engine
// itself never uploads anything - this is the only place a network request
// happens for contributed images, and it only happens after a person has
// looked at the specific image and chosen to send it.

const fs = require("fs");
const path = require("path");
const { getQueueDir } = require("./paths");

const QUEUE_DIR = getQueueDir();
const ID_PATTERN = /^[0-9A-Za-z_-]+$/; // guards against a malformed/malicious id ever touching the filesystem

function ensureQueueDir() {
  fs.mkdirSync(QUEUE_DIR, { recursive: true });
}

function listIds() {
  ensureQueueDir();
  return fs
    .readdirSync(QUEUE_DIR)
    .filter((name) => name.endsWith(".json") && name !== "state.json")
    .map((name) => name.slice(0, -".json".length))
    .sort();
}

function pendingCount() {
  return listIds().length;
}

function pathsFor(id) {
  if (!ID_PATTERN.test(id)) throw new Error(`invalid contribution id: ${id}`);
  return {
    imagePath: path.join(QUEUE_DIR, `${id}.jpg`),
    metaPath: path.join(QUEUE_DIR, `${id}.json`),
  };
}

function listPending() {
  return listIds()
    .map((id) => {
      const { imagePath, metaPath } = pathsFor(id);
      if (!fs.existsSync(imagePath)) return null; // orphaned metadata, shouldn't normally happen

      let metadata = {};
      try {
        metadata = JSON.parse(fs.readFileSync(metaPath, "utf-8"));
      } catch {
        // Corrupt metadata - still show the image, just without detail.
      }

      const imageBuffer = fs.readFileSync(imagePath);
      const dataUrl = `data:image/jpeg;base64,${imageBuffer.toString("base64")}`;

      return { id, dataUrl, metadata };
    })
    .filter(Boolean);
}

function reject(id) {
  const { imagePath, metaPath } = pathsFor(id);
  fs.rmSync(imagePath, { force: true });
  fs.rmSync(metaPath, { force: true });
}

async function approve(id) {
  const endpoint = process.env.REARAWARE_CONTRIBUTE_URL;
  const apiKey = process.env.REARAWARE_CONTRIBUTE_KEY;
  if (!endpoint || !apiKey) {
    throw new Error("Contribution upload isn't configured (REARAWARE_CONTRIBUTE_URL/KEY missing)");
  }

  const { imagePath, metaPath } = pathsFor(id);
  const imageBuffer = fs.readFileSync(imagePath);
  const metadataRaw = fs.existsSync(metaPath) ? fs.readFileSync(metaPath, "utf-8") : "{}";

  const form = new FormData();
  form.append("image", new Blob([imageBuffer], { type: "image/jpeg" }), `${id}.jpg`);
  form.append("metadata", metadataRaw);

  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "X-RearAware-Key": apiKey },
    body: form,
  });

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Upload failed (${response.status}): ${body}`);
  }

  fs.rmSync(imagePath, { force: true });
  fs.rmSync(metaPath, { force: true });
}

module.exports = { listPending, pendingCount, approve, reject };
