// Helpers that reproduce the few Python string behaviours the reference relies on, so the
// port matches it exactly. JS strings are UTF-16; every length here is in code points.

// Python str.isspace(): JS \s plus U+0085 and U+001C..U+001F, minus U+FEFF.
export function isPySpace(c) {
  return (
    (c >= 0x09 && c <= 0x0d) ||
    (c >= 0x1c && c <= 0x20) ||
    c === 0x85 ||
    c === 0xa0 ||
    c === 0x1680 ||
    (c >= 0x2000 && c <= 0x200a) ||
    c === 0x2028 ||
    c === 0x2029 ||
    c === 0x202f ||
    c === 0x205f ||
    c === 0x3000
  );
}

export function pyRstrip(s) {
  let end = s.length;
  while (end > 0 && isPySpace(s.charCodeAt(end - 1))) end--;
  return s.slice(0, end);
}

export function pyStrip(s) {
  let start = 0;
  while (start < s.length && isPySpace(s.charCodeAt(start))) start++;
  return pyRstrip(s.slice(start));
}

function isLineBreak(c) {
  return (
    c === 0x0a || c === 0x0d || c === 0x0b || c === 0x0c ||
    c === 0x1c || c === 0x1d || c === 0x1e || c === 0x85 || c === 0x2028 || c === 0x2029
  );
}

// Python str.splitlines(): splits on more than LF (spec section 11, quirk 3).
export function pySplitLines(s) {
  const out = [];
  let start = 0;
  for (let i = 0; i < s.length; ) {
    const c = s.charCodeAt(i);
    if (isLineBreak(c)) {
      out.push(s.slice(start, i));
      i += c === 0x0d && s.charCodeAt(i + 1) === 0x0a ? 2 : 1;
      start = i;
      continue;
    }
    i++;
  }
  if (start < s.length) out.push(s.slice(start));
  return out;
}

// Length in code points.
export function cpLen(s) {
  let n = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff && i + 1 < s.length) {
      const d = s.charCodeAt(i + 1);
      if (d >= 0xdc00 && d <= 0xdfff) i++;
    }
    n++;
  }
  return n;
}

// Index just after the first n code points.
export function cpIndex(s, n) {
  let i = 0;
  for (let k = 0; k < n && i < s.length; k++) {
    const c = s.charCodeAt(i);
    i += c >= 0xd800 && c <= 0xdbff && i + 1 < s.length ? 2 : 1;
  }
  return i;
}

const lenient = new TextDecoder('utf-8', { ignoreBOM: true });
const strict = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });

// bytes.decode("utf-8", errors="replace"): WHATWG decoding replaces maximal subparts, like Python.
export const decodeReplace = (buf) => lenient.decode(buf);

export function decodeStrict(buf) {
  try {
    return strict.decode(buf);
  } catch {
    return null;
  }
}

// repr() for plain strings, enough for error messages.
export function pyRepr(s) {
  let q = "'";
  if (s.includes("'") && !s.includes('"')) q = '"';
  let out = q;
  for (const ch of s) {
    const c = ch.codePointAt(0);
    if (ch === q || ch === '\\') out += '\\' + ch;
    else if (ch === '\n') out += '\\n';
    else if (ch === '\r') out += '\\r';
    else if (ch === '\t') out += '\\t';
    else if (c < 0x20 || c === 0x7f) out += '\\x' + c.toString(16).padStart(2, '0');
    else out += ch;
  }
  return out + q;
}
