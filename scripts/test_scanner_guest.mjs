// Guard: scanning signed out keeps its promise — nothing is uploaded.
//
//   node scripts/test_scanner_guest.mjs
//
// A guest can scan (2026-09-27). The notice they accept says no photo and no
// scan data leave the device, and the privacy page and the Help page repeat it.
// Every way that promise breaks is silent: an upload call that reads `user`
// instead of the snap's own flag fires once the native app signs in in place; a
// consent check that only ever sets `true` leaves the camera running on a guest's
// acceptance under an account that never saw the upload notice; a session
// telemetry row reads whoever is signed in when the camera STOPS. So the wiring
// is pinned here, at source, along with the three copy places saying the same.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..");
const HTML = fs.readFileSync(path.join(REPO, "Index.html"), "utf8").replace(/\r\n/g, "\n");
const PRIV = fs.readFileSync(path.join(REPO, "privacy.html"), "utf8").replace(/\r\n/g, "\n");

let fails = 0;
const check = (cond, msg) => { console.log((cond ? "  ok    " : "  FAIL  ") + msg); if (!cond) fails++; };
const between = (a, b) => {
  const i = HTML.indexOf(a); if (i < 0) return "";
  const j = HTML.indexOf(b, i + a.length); return j < 0 ? "" : HTML.slice(i, j);
};

// ---- the shutter is open to guests, and their snaps are marked --------------
const snap = between("  const snapForQA = useCallback(() => {", "  }, [user, onSignIn]);");
check(snap.length > 0, "found snapForQA");
check(!/if\(!user\)\{ onSignIn/.test(snap), "a signed-out tap snaps instead of bouncing to sign-in");
check(/const guest = !userRef\.current;/.test(snap), "each snap records whether it was taken signed out");
check(/const job = \{ rid, guest,/.test(snap), "…onto the job that will do the upload");
check(/\.\.\.\(guest \? \{ guest: true \} : null\)/.test(snap), "…and onto the row, which a label write reads");

// ---- nothing a guest snapped is ever sent --------------------------------------
check(/if\(rectBlob && !job\.guest\) uploadSample\(/.test(HTML),
  "the snap's upload is gated on the SNAP's flag, not on who is signed in by the time it runs");
const label = between("  const labelSample = (row, patch) => {", "  const flushPendingLabel");
check(/if\(row\.guest\) return;/.test(label), "a correction to a guest's row writes no label (and never pends one)");
const mount = between("  // mount: index + camera + worker", "  // post the rectified card to the OCR worker");
check(/const sessionUser = userRef\.current;/.test(mount) && /u = sessionUser;/.test(mount) && !/u = userRef\.current/.test(mount),
  "session telemetry belongs to whoever STARTED the camera, so a guest session sends none");

// ---- two notices, two keys --------------------------------------------------------
const consent = between("  const scanFlagKey = (base) =>", "  const writeConsent = (patch) => {");
check(/if\(!user\)\{[\s\S]{0,260}SCAN_GUEST_OK_KEY[\s\S]{0,120}return;/.test(consent),
  "signed out reads the guest notice's own key and fetches nothing");
check(/setConsentOk\(local\);/.test(consent) && !/if\(local\) setConsentOk\(true\);/.test(consent),
  "signed in sets consent EITHER way, so a guest's acceptance never carries into the account");
check(/const acceptGuest = \(\) => \{\s*try \{ localStorage\.setItem\(SCAN_GUEST_OK_KEY/.test(HTML),
  "accepting the guest notice writes the guest key, never the account's");
check(/const consentPanel = !user \? guestPanel :/.test(HTML), "a guest is shown the guest notice");

// ---- saving: the list survives the sign-in trip ------------------------------------
const save = between("  const qaSignInToSave = async () => {", "  const qaSaveToCollection");
check(/await idbSet\(SCAN_GUEST_SESSION[\s\S]*scanResumeMark\(true\);[\s\S]*onSignIn\(\);/.test(save),
  "the list is WRITTEN (awaited) before sign-in leaves the page, then the resume flag, then sign-in");
check(/if\(!user\)\{ qaSignInToSave\(\); return; \}/.test(between("  const qaSaveToCollection = async () => {", "if(qaSaving)")),
  "a guest's Add-to-collection routes through the save-and-sign-in path");
const restore = between("  const qaFresh = (s) =>", "  const qaGuestKeyUsedRef = useRef(false);");
check(/await idbSet\(qaPersistKey, \{ t: Date\.now\(\), rows \}\);\s*idbDel\(SCAN_GUEST_SESSION\);/.test(restore),
  "moving a guest list to the account writes the account copy BEFORE dropping the guest one");
check(/qaPersistKey = SCANNER_QA_ONLY \? \(user \? "scanSession:" \+ user\.id : SCAN_GUEST_SESSION\)/.test(HTML),
  "a guest list and an account list never share a key (the account's is never shown signed out)");

// ---- coming back ----------------------------------------------------------------------
const userDecl = HTML.indexOf("const [user,setUser]=useState(null);");
const reopen = HTML.indexOf("if(!user || scanOpen || !scanResumeRead()) return;");
check(userDecl > 0 && reopen > userDecl,
  "the app's reopen effect sits BELOW `user` (a deps array above it is a TDZ ReferenceError)");
check(/const reviewOnly = gated && qaResume && qaReviewing;/.test(HTML)
  && /\$\{reviewOnly \? qaReviewPanel :/.test(HTML),
  "a returning guest reaches the review screen before the upload notice — saving opens no camera");

// ---- the three copy places say the same thing -------------------------------------------
// The notice is translated, so the English sits in its _tRich key (**bold** = <b>).
check(/You're signed out, so (<b>|\*\*)nothing is uploaded(<\/b>|\*\*)/.test(HTML), "the in-scanner guest notice says nothing is uploaded");
check(/<strong>Signed out, nothing is uploaded\.<\/strong>/.test(PRIV), "privacy.html#scanner says it");
check(/<strong>Signed out, nothing is uploaded<\/strong>/.test(HTML) && !/in one go\. Sign-in required\./.test(HTML),
  "the Help page says it, and no longer says sign-in is required to scan");

console.log(fails ? `\n${fails} failed` : "\nall passed");
process.exit(fails ? 1 : 0);
