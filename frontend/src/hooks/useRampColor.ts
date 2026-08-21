import { useEffect, useState } from "react";

/**
 * 안전 등급 램프 색을 CSS 에서 읽는다.
 *
 * Three.js 머티리얼은 CSS 변수를 읽지 못한다. 그래서 예전에는 3D 트윈이 색을
 * 직접 적어 뒀고, global.css 의 램프가 개정되자 2D 평면도와 색이 갈라졌다.
 * 값을 다시 맞추는 대신 읽어오게 바꾼 이유다 — 다시 갈라질 수 없다.
 *
 * 테마 토글은 `document.documentElement.dataset.theme` 를 바꾸므로 그 속성을
 * 지켜본다. 이게 없으면 라이트 테마로 바꿔도 3D 경로만 다크 색으로 남는다.
 */
export function useRampColor(varName: string, fallback: string): string {
  const [color, setColor] = useState(fallback);

  useEffect(() => {
    const root = document.documentElement;
    const read = () => {
      const value = getComputedStyle(root).getPropertyValue(varName).trim();
      // 변수가 없으면 fallback 을 유지한다. 빈 문자열을 머티리얼에 넘기면
      // three 가 검정으로 해석해서 경로가 배경에 묻힌다.
      setColor(value || fallback);
    };
    read();
    const observer = new MutationObserver(read);
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, [varName, fallback]);

  return color;
}
