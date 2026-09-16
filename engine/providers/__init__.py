"""에셋 제공자 추상화 (DV3).

이미지/영상/TTS 를 인터페이스 뒤에 두고 config 로 라우팅한다(engine/llm.py 의 모델 라우팅과 동일 발상).
P-V0 기본은 'placeholder'(키 불필요·조립 검증). 실배선(Gemini 이미지·Edge TTS·힉스필드 I2V)은 P-V1.
"""

from . import image, tts, video  # noqa: F401
