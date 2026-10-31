# 许可说明

这个仓库里的东西分两类，许可是分开的，**不能混为一谈**。

---

## 一、代码

`render_api.py`、`server.py`、`studio.html`、`musicxml.py`、`fetch_samples.py`、`gen_intro_video.py`

采用 **MIT License**。你可以自由使用、修改、分发，保留版权声明即可。

---

## 二、采样（不在仓库内）

采样文件体积大（约 50 MB），不入库，由 `fetch_samples.py` 从各自的上游仓库下载。
**下载与使用即受各自许可约束**——其中两套是 CC BY，**必须署名**。

| 音源 | 上游仓库 | 许可 | 署名要求 |
|---|---|---|---|
| **二胡** | [`sfzinstruments/aliexpress-erhu`](https://github.com/sfzinstruments/aliexpress-erhu) | **CC0 1.0** | 无需署名，可自由使用 |
| **编钟** | [`wizonce9/A-Novel-Physical-Modeling-Approach-for-Sound-Synthesis-of-Chinese-Chime-Bells`](https://github.com/wizonce9/A-Novel-Physical-Modeling-Approach-for-Sound-Synthesis-of-Chinese-Chime-Bells) | **MIT** | 保留版权与许可声明 |
| **长笛** | [`sfzinstruments/Ixox.Flute`](https://github.com/sfzinstruments/Ixox.Flute) | **CC BY 4.0** | ⚠️ **必须署名** |
| **钢琴** | [`sfzinstruments/SalamanderGrandPiano`](https://github.com/sfzinstruments/SalamanderGrandPiano) | **CC BY 3.0** | ⚠️ **必须署名**（Alexander Holm） |

### 编钟采样的录制鸣谢

武汉音乐学院 **Nie Kaiwen**、**Li Yunpeng** 提供采样；**Weijia Yang** 主持项目（论文《A Novel Physical Modeling Approach for Sound Synthesis of Chinese Chime Bells》）。

---

## 三、如果你要分发用这些采样做的音频

- **只含二胡**：无附加义务（CC0）
- **只含编钟**：保留 MIT 声明
- **含长笛或钢琴**：**必须在发布页面写明素材来源与作者**，否则违反 CC BY

推荐在作品说明里附一句：

> 采样素材：Salamander Grand Piano（Alexander Holm, CC BY 3.0）、Ixox Flute（CC BY 4.0）、
> 曾侯乙编钟（Nie Kaiwen / Li Yunpeng 录制, MIT）、二胡（aliexpress-erhu, CC0）

---

## 四、关于 432 Hz

本项目只主张**可验证的部分**：频率基准（A4 = 432.00 Hz）、逐音校准精度、音色与文化的对应关系。

**不主张任何生理或医疗功效。** 已查过 PubMed 上全部 11 篇相关文献（2019–2025），
均为小样本试点研究，没有一篇能支撑"432 Hz 对人体更好"的结论。
