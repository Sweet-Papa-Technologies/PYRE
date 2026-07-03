<template>
  <div class="card glass">
    <div class="skeleton line short" />
    <div class="skeleton line title" />
    <div class="skeleton line" />
    <div class="skeleton line" />
    <div class="skeleton line med" />
    <div class="chips">
      <div class="skeleton chip" />
      <div class="skeleton chip" />
    </div>
  </div>
</template>

<style scoped>
.card {
  padding: 1.5rem;
}
.line {
  height: 12px;
  margin-bottom: 0.7rem;
}
.line.short {
  width: 40%;
  height: 10px;
}
.line.title {
  height: 22px;
  width: 75%;
  margin-bottom: 1rem;
}
.line.med {
  width: 60%;
}
.chips {
  display: flex;
  gap: 0.5rem;
  margin-top: 1rem;
}
.chip {
  width: 60px;
  height: 24px;
  border-radius: 999px;
}
</style>
