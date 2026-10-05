// ⚠ A TEST (Zaven, 2026-10-05): can /card show the card bigger than an embed
// allows? Discord fits an embed's picture inside ~400 x 300, so a tall card
// comes out ~200 px wide however it is drawn. /card's `layout` option tries
// the two ways out of the embed, to compare in a real channel; the loser is
// deleted with this file.
//
//   embed — today's reply, unchanged.
//   image — the same embed with its picture taken OUT of it: the uploaded file
//           is left on the message as a plain attachment, which Discord draws
//           on its own (bigger, it is thought) next to the embed.
//   big   — Discord's newer message layout ("Components V2"): the embed becomes
//           a container of text blocks, the picture a media gallery, the
//           buttons and menus rows inside it. A V2 message can carry no embed
//           and can never go back to being one.
//
// A button on a test reply keeps its layout: the layout is read off the
// message the button sits on (layoutOfMessage), so no custom_id changes.
export const LAYOUTS = ["embed", "image", "big"];
export const IS_COMPONENTS_V2 = 1 << 15;

export function layoutOfMessage(msg) {
  if (!msg) return "embed";
  if (Number(msg.flags) & IS_COMPONENTS_V2) return "big";
  const e = (msg.embeds || [])[0];
  if (e && !e.image && (msg.attachments || []).some((a) => /^image\//.test(a.content_type || "") || /\.(webp|png|jpe?g)$/i.test(a.filename || ""))) return "image";
  return "embed";
}

// body: a reply as patchOriginal would send it (embeds may already point at
// uploaded attachment:// files). Returns the body to send in that layout.
export function applyLayout(body, layout) {
  if (!body || layout === "embed" || !Array.isArray(body.embeds) || !body.embeds.length) return body;
  if (layout === "image") {
    const embeds = body.embeds.map((e) => ({ ...e }));
    const e = embeds[0];
    // Only an UPLOADED picture can stand on its own; a linked one stays put.
    if (e.image && /^attachment:\/\//.test(e.image.url || "")) delete e.image;
    return { ...body, embeds };
  }
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
  const out = { components: [container], flags: IS_COMPONENTS_V2 };
  if (body.attachments) out.attachments = body.attachments;
  if (body.allowed_mentions) out.allowed_mentions = body.allowed_mentions;
  return out;
}
