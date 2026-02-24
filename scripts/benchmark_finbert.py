"""Dell 서버 (VM) CPU에서 FinBERT 성능 측정"""
import time
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

print("📊 FinBERT CPU 벤치마크")
print(f"PyTorch: {torch.__version__}")
print(f"CPU 스레드: {torch.get_num_threads()}")

tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
model.eval()

headlines = [
    "Apple reports record quarterly revenue beating expectations",
    "Fed signals aggressive rate hikes amid persistent inflation",
    "Tesla shares plunge 12% after disappointing delivery numbers",
    "Nvidia surpasses trillion dollar valuation on AI demand",
    "Unemployment claims rise sharply to six month high",
] * 20  # 100건

print(f"\n테스트: {len(headlines)}건 헤드라인 배치 처리")

# Warm-up
inputs = tokenizer(headlines[:5], padding=True, truncation=True, 
                    max_length=512, return_tensors="pt")
with torch.no_grad():
    model(**inputs)

# 실제 벤치마크 (3회 평균)
times = []
for trial in range(3):
    inputs = tokenizer(headlines, padding=True, truncation=True,
                       max_length=512, return_tensors="pt")
    start = time.time()
    with torch.no_grad():
        outputs = model(**inputs)
        probs = torch.softmax(outputs.logits, dim=-1)
    elapsed = time.time() - start
    times.append(elapsed)
    print(f"  Trial {trial+1}: {elapsed:.2f}s ({len(headlines)/elapsed:.1f} 건/초)")

avg = sum(times) / len(times)
print(f"\n{'='*40}")
print(f"✅ 평균: {avg:.2f}초 → {len(headlines)/avg:.1f} 건/초")
if len(headlines)/avg >= 10:
    print("🎉 목표 달성! (10건/초 이상)")
else:
    print("⚠️ 목표 미달 (10건/초 미만) — 배치 크기 조정 필요")

# 샘플 결과 출력
labels = ["positive", "negative", "neutral"]
for i in range(5):
    p = probs[i].numpy()
    label = labels[p.argmax()]
    score = float(p[0] - p[1])  # positive - negative
    print(f"  {label:>8} ({score:+.3f}): {headlines[i][:60]}")
