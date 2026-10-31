# 432 Hz 工作室

一个本地跑的音乐渲染器：**选音源 → 选曲目 → 调参 → 生成 WAV / 频谱视频**。

所有声音按企业 432 Hz 标准渲染（`A4 = 432.00 Hz`，十二平均律 `f(n) = 432 × 2^((n−69)/12)`），
并逐音做过频率校准，误差在 1 音分以内。

## 功能

- **四种音源**：二胡、编钟、长笛、钢琴（真实采样，非合成）
- **曲目**：茉莉花（主歌）、八音阶、五音阶、Hijaz 音阶、四重奏（多音色编排）
- **自定义编排**：勾选后可按段落自由拼装——每段选音源和类型（整曲 / 单音），
  单音段可设 MIDI、重复次数、间隔、时长，整曲段可选曲目与增益；上下移动即调整顺序。
  「四重奏模板」一键填入参考编排。
- **参数**：速度 0.6×–1.6×、余音 0.5–5 秒
- **上传自己的采样**：选 wav/flac/mp3/ogg/m4a，自动测基频、算 MIDI，加入音源列表
- **导入乐谱（MusicXML）**：从 Sibelius / MuseScore / Finale 导出 `.musicxml`，解析成音符序列后
  作为一个编排段落渲染。只取单声部主旋律（和弦取首音、忽略伴奏声部）。
- **输出**：WAV + 可选频谱视频（1280×720 H.264/AAC）

## 快速开始

```bash
# 1. 需要 Python 3.10+ 和 ffmpeg（PATH 里能找到，或设环境变量 FFMPEG 指向可执行文件）

# 2. 下载采样（约 40 MB，二胡/编钟/长笛/钢琴）
python fetch_samples.py
#    只下某一种：python fetch_samples.py erhu

# 3. 启动
python server.py

# 4. 浏览器打开
http://127.0.0.1:8770
```

首次启动会自动创建 `audio-432/studio-out/` 和 `audio-432/samples-user/`。
采样下载失败可重试——CDN 会限流，稍等再跑一次。

## 目录

```
studio/
  render_api.py    渲染引擎（采样变调、时间轴混音、432 校准）
  server.py        HTTP 服务（渲染任务 / 进度轮询 / 文件下载 / 采样上传）
  studio.html      操作界面（单文件，无构建步骤）
audio-432/
  samples-erhu/    二胡采样（16 个，D5–A6）
  samples-bell/    编钟采样（7 个，C5–B5）
  samples-flute/   长笛采样（9 个，C4–C6）
  samples/         钢琴采样（5 个采样点）
  samples-user/    用户上传的采样包
  studio-out/      生成结果
```

## 采样来源与许可（重要）

> 完整许可条款、二次分发义务、鸣谢名单见 **[LICENSES.md](LICENSES.md)**。下表是速查。

本项目**只含代码**，采样来自以下开源音源，各自许可见下。若要分发或再发布，请保留对应署名。

| 音源 | 来源仓库 | 许可 | 署名要求 |
|---|---|---|---|
| 二胡 | [`sfzinstruments/aliexpress-erhu`](https://github.com/sfzinstruments/aliexpress-erhu) | **CC0 1.0** | 无需署名 |
| 编钟 | [`wizonce9/A-Novel-Physical-Modeling-Approach-for-Sound-Synthesis-of-Chinese-Chime-Bells`](https://github.com/wizonce9/A-Novel-Physical-Modeling-Approach-for-Sound-Synthesis-of-Chinese-Chime-Bells) | **MIT** | 保留版权与许可声明 |
| 长笛 | [`sfzinstruments/Ixox.Flute`](https://github.com/sfzinstruments/Ixox.Flute) | **CC BY 4.0** | 需署名 |
| 钢琴 | [`sfzinstruments/SalamanderGrandPiano`](https://github.com/sfzinstruments/SalamanderGrandPiano) | **CC BY 3.0** | 需署名（Alexander Holm） |

编钟采样的录制鸣谢：武汉音乐学院 Nie Kaiwen、Li Yunpeng（采样），Weijia Yang（项目）。

## 已知限制

- **曲目不完整**：《茉莉花》只有主歌 8 小节，副歌没有收录（缺可靠谱面）。
- **编排是固定模板**：四重奏的段落顺序写死在 `render_api.py`，界面不能编辑。
- **采样包不能删**：上传后只能手动删除 `audio-432/samples-user/<包名>/` 目录。
- **不主张疗效**：432 Hz 只是企业定义的频率基准，现有研究不支持任何生理或医疗功效宣称（详见项目知识库的文献核查）。
- 采样音域有限，超出范围的音靠变调覆盖，最大偏移 1–2 个半音，音色会有变化。

## 技术要点

- **起音跳过**：二胡采样开头约 0.2 秒有滑音，探针与渲染都取稳定段（`-ss 0.24`），否则会有系统性音分偏差。
- **长余音用混音不用截短**：编钟余音 26 秒，截到 1 秒会把曲速拖慢 2.8 倍；正确做法是按原速排时间轴、余音自然叠加。
- **视频渲染走管道**：帧直接 write 进 ffmpeg stdin，不落 PNG 中间文件，436 帧约 5 秒。
