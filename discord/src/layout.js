// /card's reply in Discord's newer message layout ("Components V2"), chosen
// 2026-10-05 after a side-by-side test in a real channel. An embed fits its
// picture inside ~400 x 300, so a tall card came out ~200 px wide however it
// was drawn; a V2 media gallery shows it much bigger. The test's other option
// — the picture as a loose attachment beside the embed — lost and is gone.
//
//   embed — every other reply, and /price (a chart is wide; an embed fits it).
//   big   — the embed becomes a container of text blocks, the picture a media
//           gallery, the buttons and menus rows inside it. A V2 message can
//           carry no embed and can never go back to being one.
//
// A button keeps the layout of the message it sits on (layoutOfMessage), so
// "Price chart" on a /card reply answers in V2 and "Card image" on a /price
// reply stays an embed. No custom_id changes.
export const LAYOUTS = ["embed", "big"];
export const IS_COMPONENTS_V2 = 1 << 15;

export function layoutOfMessage(msg) {
  if (!msg) return "embed";
  return Number(msg.flags) & IS_COMPONENTS_V2 ? "big" : "embed";
}

// body: a reply as patchOriginal would send it (embeds may already point at
// uploaded attachment:// files). Returns the body to send in that layout.
export function applyLayout(body, layout) {
  if (!body || layout === "embed" || !Array.isArray(body.embeds) || !body.embeds.length) return body;
  if (layout === "big") return toComponentsV2(body);
  return body;
}

const clip = (s, n) => { s = String(s || ""); return s.length <= n ? s : s.slice(0, n - 1) + "…"; };

export function toComponentsV2(body) {
  const e = body.embeds[0];
  const parts = [];
  const head = [];
  if (e.title) head.push(e.url ? `### [${e.title}](${e.url})` : `### ${e.title}`);
  if (e.description) head.push(e.description);
  const headText = { type: 10, content: clip(head.join("\n"), 3000) || "​" };
  if (e.thumbnail && e.thumbnail.url) {
    parts.push({ type: 9, components: [headText], accessory: { type: 11, media: { url: e.thumbnail.url } } });
  } else parts.push(headText);
  if (e.fields && e.fields.length) {
    parts.push({ type: 10, content: clip(e.fields.map((f) => `**${f.name}** · ${String(f.value).replace(/\n/g, " · ")}`).join("\n"), 600) });
  }
  if (e.image && e.image.url) parts.push({ type: 12, items: [{ media: { url: e.image.url } }] });
  if (e.footer && e.footer.text) parts.push({ type: 10, content: clip("-# " + e.footer.text, 300) });
  for (const row of body.components || []) parts.push(row);
  const container = { type: 17, components: parts };
  if (e.color != null) container.accent_color = e.color;
  // A V2 message has no `content`; a note above the reply ("Example: …")
  // becomes a text block of its own, above the container.
  const top = body.content ? [{ type: 10, content: clip(body.content, 1000) }] : [];
  const out = { components: [...top, container], flags: IS_COMPONENTS_V2 };
  if (body.attachments) out.attachments = body.attachments;
  if (body.allowed_mentions) out.allowed_mentions = body.allowed_mentions;
  return out;
}
