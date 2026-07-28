#!/usr/bin/env bash
# 本地生成 N 分钟中文测试音频(纯本地,零网络,用 macOS say + ffmpeg)。
# 用途:测离线上传的"最长时长上限"和"解析速度"。内容为单人 TTS,测不出多人说话人分离。
#
# 用法:
#   bash scripts/gen_chinese_audio.sh 60          # 生成 60 分钟,输出 ./test_zh_60min.mp3
#   bash scripts/gen_chinese_audio.sh 30 test.wav # 生成 30 分钟,自定义输出名
set -euo pipefail

MINUTES="${1:-60}"
OUT="${2:-./test_zh_${MINUTES}min.mp3}"
SECONDS_TOTAL=$((MINUTES * 60))

# 一段较长的中文文本,循环念直到够时长。内容是公共领域科普性质,无版权问题。
TEXT="大家好,欢迎收听本次测试音频。我们今天来讨论一个关于语音识别技术的话题。语音识别,也就是把人说的话转换成文字的过程,在过去几年里取得了非常大的进步。从早期的基于隐马尔可夫模型的方法,到现在基于深度学习的端到端模型,识别准确率有了显著提升。目前主流的语音识别系统大多采用 Transformer 架构,它能够更好地处理长距离依赖关系,在处理长音频时表现更加稳定。除了识别准确率,实时性也是衡量语音识别系统的重要指标。在一些对延迟敏感的场景里,比如实时字幕和会议记录,系统需要在尽量短的时间内给出结果。为了做到这一点,工程师们通常会对音频进行分段处理,每段单独识别,然后再把结果拼接起来。但分段也带来新的挑战,比如如何避免把一句话切到两段里去。常见的做法是使用语音活动检测,也就是常说的 VAD,先找到人说话的起止点,再按这些边界来切分,这样能尽量保证一句话的完整。在说话人识别方面,系统会提取每个人声音的特征,也就是声纹,然后在向量数据库里做相似度匹配,判断这段话是谁说的。这套流程在多人会议里尤其有用,因为需要区分不同的人分别说了什么。当然,语音识别并不是万能的,它仍然会受到背景噪声、口音、说话人重叠等因素的影响,在复杂环境下准确率会下降。所以好的系统通常会做一些后处理,比如用语言模型来纠正识别错误,或者用置信度来标记不太确定的部分供人工复核。今天我们就先聊到这里,感谢收听。"

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

echo "生成中文 TTS 片段..."
say -v Tingting -o "$TMP_DIR/seg.aiff" "$TEXT"
# 转成 16k 单声道 wav(与项目采样率一致,最干净)
ffmpeg -y -loglevel error -i "$TMP_DIR/seg.aiff" -ar 16000 -ac 1 "$TMP_DIR/seg.wav"

SEG_DUR=$(ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$TMP_DIR/seg.wav")
echo "单段时长: ${SEG_DUR}s"

# 算循环次数(向上取整,保证 >= 目标时长)
LOOPS=$(python3 -c "import math; print(max(1, math.ceil($SECONDS_TOTAL / $SEG_DUR)))")
echo "循环 $LOOPS 次拼到约 ${MINUTES} 分钟..."

# 生成循环列表文件
: > "$TMP_DIR/list.txt"
for i in $(seq 1 "$LOOPS"); do
  echo "file '$TMP_DIR/seg.wav'" >> "$TMP_DIR/list.txt"
done

# 拼接并裁剪到精确时长,输出 mp3(也可直接输出 wav,改扩展名即可)
ffmpeg -y -loglevel error -f concat -safe 0 -i "$TMP_DIR/list.txt" -t "$SECONDS_TOTAL" -c:a libmp3lame -b:a 64k "$OUT"

FINAL_DUR=$(ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$OUT")
SIZE=$(stat -f%z "$OUT" 2>/dev/null || stat -c%s "$OUT")
MINS=$(python3 -c "print(f'{$FINAL_DUR/60:.1f}')")
MB=$(python3 -c "print(f'{$SIZE/1048576:.1f}')")
echo
echo "✅ 完成: $OUT"
echo "   时长: ${MINS} 分钟 (${FINAL_DUR} 秒)"
echo "   大小: ${MB} MB"
echo
echo "上传到项目测试:"
echo "   curl -k -F \"file=@$OUT\" https://127.0.0.1:8888/v1/meetings/upload"
