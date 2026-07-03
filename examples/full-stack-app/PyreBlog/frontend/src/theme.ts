import { definePreset } from '@primevue/themes'
import Aura from '@primevue/themes/aura'

// PyrePress preset: Aura re-tuned to the PYRE flame palette.
// Primary = ember orange; dark surfaces = deep space navy (banner #0d1117-ish).
export const PyrePreset = definePreset(Aura, {
  semantic: {
    primary: {
      50: '#fff7ed',
      100: '#ffedd5',
      200: '#fed7aa',
      300: '#fdba74',
      400: '#ff8a3c',
      500: '#f97316',
      600: '#ea580c',
      700: '#c2410c',
      800: '#9a3412',
      900: '#7c2d12',
      950: '#431407',
    },
    colorScheme: {
      light: {
        primary: {
          color: '{primary.600}',
          contrastColor: '#ffffff',
          hoverColor: '{primary.700}',
          activeColor: '{primary.700}',
        },
        highlight: {
          background: '{primary.50}',
          focusBackground: '{primary.100}',
          color: '{primary.700}',
          focusColor: '{primary.800}',
        },
      },
      dark: {
        surface: {
          0: '#ffffff',
          50: '#f4f6f9',
          100: '#e8ebf1',
          200: '#d3d8e2',
          300: '#aab3c5',
          400: '#7e89a3',
          500: '#5b667f',
          600: '#434d63',
          700: '#313a4d',
          800: '#1e2434',
          900: '#141a2c',
          950: '#0b0e18',
        },
        primary: {
          color: '{primary.400}',
          contrastColor: '#1c1206',
          hoverColor: '{primary.300}',
          activeColor: '{primary.300}',
        },
        highlight: {
          background: 'color-mix(in srgb, {primary.400}, transparent 84%)',
          focusBackground: 'color-mix(in srgb, {primary.400}, transparent 76%)',
          color: 'rgba(255,255,255,.87)',
          focusColor: 'rgba(255,255,255,.87)',
        },
      },
    },
  },
})
