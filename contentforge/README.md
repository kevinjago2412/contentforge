# ContentForge

YouTube URL -> transcript -> LLM kurasi -> top-N clip Shorts 9:16 (1080x1920) dengan subtitle kebakar.

## Setup GitHub Actions (sekali saja)

1. Bikin repo baru di GitHub (public = gratis 2000 menit/bulan, private juga boleh).
2. Push repo ini. Dari hape bisa pake Termux git atau app seperti GitFoxy / MGit.
3. Di GitHub web: **Settings -> Secrets and variables -> Actions -> New repository secret**, tambahkan 3 secrets:
   - `OPENAI_API_KEY` — API key LLM lu
   - `OPENAI_BASE_URL` — mis. `https://bandelbanget.xyz/v1`
   - `MODEL` — mis. `kimi-k2.7-code`
4. Selesai. Workflow "Render Clips" muncul di tab **Actions**.

## Jalanin (dari browser hape)

GitHub -> repo lu -> tab **Actions** -> **Render Clips** -> **Run workflow** -> isi URL YouTube -> **Run**.

Hasil: setelah selesai, download artifact `clips-<run_id>` berisi MP4 + `result.json`.
Artifact tersimpan 14 hari.

## Jalanin (dari terminal / bot, via HTTP)

Kalau lu bikin PAT (Settings -> Developer settings -> Personal access tokens, scope `repo`),
bisa trigger tanpa buka browser:

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer <PAT>" \
  https://api.github.com/repos/<user>/<repo>/dispatches \
  -d '{"event_type":"render-clips","client_payload":{"url":"https://www.youtube.com/watch?v=XXXX"}}'
```

## Input yang tersedia

| Input | Default | Keterangan |
|---|---|---|
| url | (wajib) | URL YouTube video/live/VOD |
| layout | gaming | `default` (podcast center-crop) / `gaming` (facecam atas + gameplay bawah) |
| top_n | 5 | jumlah clip |
| subtitles | true | bakar subtitle |
| lang | id | bahasa subtitle |
| chunk_duration | 600 | 600 buat livestream panjang |
| overlap | 120 | overlap antar chunk |
| gameplay_focus | 0.5 | posisi horizontal crop gameplay |
| subtitle_margin | 300 | margin bawah subtitle (px) |

## Catatan

- Facecam auto-detect (YuNet) jalan di Actions (opencv-headless).
- Biaya: cuma API LLM. GitHub Actions public repo gratis 2000 menit/bulan.
- Kalau video butuh login/age-restricted, perlu tambah cookies (belum didukung workflow ini).
