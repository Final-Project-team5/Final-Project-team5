export const BACKGROUND_MODES = { AI: 'ai', SIMPLE: 'simple' };

const MODE_SUPPORT = {
  product: {
    '1:1': [BACKGROUND_MODES.AI, BACKGROUND_MODES.SIMPLE],
    '3:1': [BACKGROUND_MODES.AI, BACKGROUND_MODES.SIMPLE],
    '3:4': [BACKGROUND_MODES.SIMPLE],
  },
  service: { '1:1': [BACKGROUND_MODES.AI] },
};

export function getSupportedBackgroundModes(businessType, aspectRatio) {
  return MODE_SUPPORT[businessType]?.[aspectRatio] || [BACKGROUND_MODES.AI];
}
