import { ref } from 'vue'

const KEY = 'pyrepress.theme'
type Theme = 'dark' | 'light'

const stored = (localStorage.getItem(KEY) as Theme) || 'dark'
const theme = ref<Theme>(stored)

function apply(t: Theme) {
  const html = document.documentElement
  html.classList.toggle('pp-dark', t === 'dark')
  html.classList.toggle('pp-light', t === 'light')
}
apply(theme.value)

export function useTheme() {
  function toggle() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    localStorage.setItem(KEY, theme.value)
    apply(theme.value)
  }
  return { theme, toggle }
}
