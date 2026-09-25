// dev aid: one frame per mark (at t+off), labelled, tiled
import { execFileSync } from "node:child_process"; import fs from "node:fs";
const [clip, out, off = "0.6", cols = "5"] = process.argv.slice(2);
const FF = process.env.LOCALAPPDATA + "/Migaku/MigakuShared/ffmpeg.exe";
const marks = JSON.parse(fs.readFileSync(`promo/calendar/clips/${clip}.marks.json`));
const tmp = out + "_parts"; fs.mkdirSync(tmp, { recursive: true });
marks.forEach((m, i) => execFileSync(FF, ["-y", "-loglevel", "error", "-ss", String(Math.max(0, m.t + +off)), "-i", `promo/calendar/clips/${clip}.mp4`, "-frames:v", "1",
  "-vf", `scale=560:-1,drawtext=fontfile='C\:/Windows/Fonts/arialbd.ttf':text='${i} ${m.name} ${m.t.toFixed(1)}':x=6:y=6:fontsize=22:fontcolor=yellow:box=1:boxcolor=black`, `${tmp}/${String(i).padStart(2, "0")}.png`]));
execFileSync(FF, ["-y", "-loglevel", "error", "-framerate", "1", "-i", `${tmp}/%02d.png`, "-vf", `tile=${cols}x${Math.ceil(marks.length / cols)}`, "-frames:v", "1", out]);
fs.rmSync(tmp, { recursive: true });
