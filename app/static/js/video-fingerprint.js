/* Compute a fast fingerprint of a video file using SHA-256 of size + first 1MB + last 1MB */
async function computeVideoFingerprint(file) {
    var CHUNK = 1024 * 1024; // 1MB
    var size = file.size;
    var header = await file.slice(0, Math.min(CHUNK, size)).arrayBuffer();
    var trailer = size > CHUNK
        ? await file.slice(Math.max(0, size - CHUNK), size).arrayBuffer()
        : new ArrayBuffer(0);
    var sizeStr = new TextEncoder().encode(String(size));
    var combined = new Uint8Array(sizeStr.byteLength + header.byteLength + trailer.byteLength);
    combined.set(new Uint8Array(sizeStr), 0);
    combined.set(new Uint8Array(header), sizeStr.byteLength);
    combined.set(new Uint8Array(trailer), sizeStr.byteLength + header.byteLength);
    var digest = await crypto.subtle.digest("SHA-256", combined);
    return Array.from(new Uint8Array(digest)).map(function(b) { return b.toString(16).padStart(2, "0"); }).join("");
}

window.computeVideoFingerprint = computeVideoFingerprint;
export { computeVideoFingerprint };
