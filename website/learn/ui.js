// Interface strings of the Learn app, one object per language. The lessons themselves are in content/<lang>/.
// To add a language: add its code and name to `langs`, a strings object below, and content/<lang>/ (same files as content/en/).
window.GGLearnUI = {
  langs: [["en", "English"], ["tr", "Türkçe"], ["es", "Español"], ["de", "Deutsch"], ["ru", "Русский"], ["zh", "中文"]],
  strings: {
    en: {
      title: "Learn Greengold", lede: "From zero to the standard library. Write code in the browser, run it, solve the exercises.",
      pickPath: "Choose your path", beginner: "I'm new to programming", dev: "I know another language",
      pathNote: "The programmer path skips the 'introduction to programming' lessons.", skipped: "skipped",
      run: "Run", stop: "Stop", reset: "Reset", check: "Check", hint: "Hint", solution: "Show solution",
      tryIt: "Try it", exercise: "Exercise", openEx: "Open in editor", quiz: "Question", next: "Next", prev: "Previous", done: "Completed",
      loading: "Loading…", ready: "Ready", building: "Building…", running: "Running…", couldNotBuild: "Could not build.",
      correct: "Correct!", wrong: "The output is not what was expected.", expected: "Expected", got: "Your output", answer: "Correct answer",
      contents: "Contents", badges: "Badges", progress: "Progress", lessons: "lessons",
      b_first_run: "First program", b_first_ex: "First exercise", b_ex10: "10 exercises", b_quiz5: "5 correct answers", b_chapter: "Chapter finished",
      cont: "Continue where you left off", start: "Start", review: "We suggest finishing this first",
      localOnly: "This example does not run in the browser; try it on your own machine.",
      ref: "Standard library reference", search: "Search: function, type, module…", modules: "Modules", results: "results", noResults: "No results.",
      openInEditor: "Try in editor", finishNeeds: "Needed to complete", stopped: "Stopped.", tooLong: "The program ran too long.", exit: "exit code"
    },
    tr: {
      title: "Greengold Öğren", lede: "Sıfırdan başlayıp standart kütüphaneye kadar. Kodu tarayıcıda yaz, çalıştır, alıştırmayı çöz.",
      pickPath: "Yolunu seç", beginner: "Yeni başlıyorum", dev: "Başka bir dil biliyorum",
      pathNote: "Programcı yolunda 'programlamaya giriş' dersleri atlanır.", skipped: "atlandı",
      run: "Çalıştır", stop: "Durdur", reset: "Sıfırla", check: "Kontrol et", hint: "İpucu", solution: "Çözümü göster",
      tryIt: "Dene", exercise: "Alıştırma", openEx: "Editörde aç", quiz: "Soru", next: "Sonraki", prev: "Önceki", done: "Tamamlandı",
      loading: "Yükleniyor…", ready: "Hazır", building: "Derleniyor…", running: "Çalışıyor…", couldNotBuild: "Derlenemedi.",
      correct: "Doğru!", wrong: "Çıktı beklenenle aynı değil.", expected: "Beklenen", got: "Senin çıktın", answer: "Doğru cevap",
      contents: "İçindekiler", badges: "Rozetler", progress: "İlerleme", lessons: "ders",
      b_first_run: "İlk program", b_first_ex: "İlk alıştırma", b_ex10: "10 alıştırma", b_quiz5: "5 doğru cevap", b_chapter: "Bölüm bitirildi",
      cont: "Kaldığın yerden devam et", start: "Başla", review: "Önce şunu bitirmeni öneririz",
      localOnly: "Bu örnek tarayıcıda çalışmaz; kendi bilgisayarında dene.",
      ref: "Standart kütüphane referansı", search: "Ara: fonksiyon, tip, modül…", modules: "Modüller", results: "sonuç", noResults: "Sonuç yok.",
      openInEditor: "Editörde dene", finishNeeds: "Tamamlamak için gerekli", stopped: "Durduruldu.", tooLong: "Program çok uzun sürdü.", exit: "çıkış kodu"
    },
    es: {
      title: "Aprende Greengold", lede: "Desde cero hasta la biblioteca estándar. Escribe código en el navegador, ejecútalo y resuelve los ejercicios.",
      pickPath: "Elige tu camino", beginner: "Soy nuevo en programación", dev: "Conozco otro lenguaje",
      pathNote: "El camino para programadores se salta las lecciones de «introducción a la programación».", skipped: "omitido",
      run: "Ejecutar", stop: "Detener", reset: "Restablecer", check: "Comprobar", hint: "Pista", solution: "Mostrar la solución",
      tryIt: "Probar", exercise: "Ejercicio", openEx: "Abrir en el editor", quiz: "Pregunta", next: "Siguiente", prev: "Anterior", done: "Completada",
      loading: "Cargando…", ready: "Listo", building: "Compilando…", running: "Ejecutando…", couldNotBuild: "No se pudo compilar.",
      correct: "¡Correcto!", wrong: "La salida no es la esperada.", expected: "Esperado", got: "Tu salida", answer: "Respuesta correcta",
      contents: "Contenido", badges: "Insignias", progress: "Progreso", lessons: "lecciones",
      b_first_run: "Primer programa", b_first_ex: "Primer ejercicio", b_ex10: "10 ejercicios", b_quiz5: "5 respuestas correctas", b_chapter: "Capítulo terminado",
      cont: "Continúa donde lo dejaste", start: "Empezar", review: "Te sugerimos terminar esto primero",
      localOnly: "Este ejemplo no se ejecuta en el navegador; pruébalo en tu propio ordenador.",
      ref: "Referencia de la biblioteca estándar", search: "Buscar: función, tipo, módulo…", modules: "Módulos", results: "resultados", noResults: "Sin resultados.",
      openInEditor: "Probar en el editor", finishNeeds: "Necesario para completar", stopped: "Detenido.", tooLong: "El programa tardó demasiado.", exit: "código de salida"
    },
    de: {
      title: "Greengold lernen", lede: "Von null bis zur Standardbibliothek. Schreibe Code im Browser, führe ihn aus und löse die Aufgaben.",
      pickPath: "Wähle deinen Weg", beginner: "Ich bin neu in der Programmierung", dev: "Ich kenne eine andere Sprache",
      pathNote: "Der Programmierer-Weg überspringt die Lektionen „Einführung in die Programmierung“.", skipped: "übersprungen",
      run: "Ausführen", stop: "Stopp", reset: "Zurücksetzen", check: "Prüfen", hint: "Hinweis", solution: "Lösung anzeigen",
      tryIt: "Ausprobieren", exercise: "Aufgabe", openEx: "Im Editor öffnen", quiz: "Frage", next: "Weiter", prev: "Zurück", done: "Abgeschlossen",
      loading: "Lädt…", ready: "Bereit", building: "Wird kompiliert…", running: "Läuft…", couldNotBuild: "Kompilieren fehlgeschlagen.",
      correct: "Richtig!", wrong: "Die Ausgabe ist nicht die erwartete.", expected: "Erwartet", got: "Deine Ausgabe", answer: "Richtige Antwort",
      contents: "Inhalt", badges: "Abzeichen", progress: "Fortschritt", lessons: "Lektionen",
      b_first_run: "Erstes Programm", b_first_ex: "Erste Aufgabe", b_ex10: "10 Aufgaben", b_quiz5: "5 richtige Antworten", b_chapter: "Kapitel abgeschlossen",
      cont: "Dort weitermachen, wo du aufgehört hast", start: "Starten", review: "Wir empfehlen, zuerst dies abzuschließen",
      localOnly: "Dieses Beispiel läuft nicht im Browser; probiere es auf deinem eigenen Rechner.",
      ref: "Referenz der Standardbibliothek", search: "Suchen: Funktion, Typ, Modul…", modules: "Module", results: "Ergebnisse", noResults: "Keine Ergebnisse.",
      openInEditor: "Im Editor ausprobieren", finishNeeds: "Zum Abschließen nötig", stopped: "Gestoppt.", tooLong: "Das Programm lief zu lange.", exit: "Exit-Code"
    },
    ru: {
      title: "Изучаем Greengold", lede: "От нуля до стандартной библиотеки. Пишите код в браузере, запускайте его и решайте упражнения.",
      pickPath: "Выберите свой путь", beginner: "Я новичок в программировании", dev: "Я знаю другой язык",
      pathNote: "Путь для программистов пропускает уроки «Введение в программирование».", skipped: "пропущено",
      run: "Запустить", stop: "Стоп", reset: "Сбросить", check: "Проверить", hint: "Подсказка", solution: "Показать решение",
      tryIt: "Попробовать", exercise: "Упражнение", openEx: "Открыть в редакторе", quiz: "Вопрос", next: "Далее", prev: "Назад", done: "Завершено",
      loading: "Загрузка…", ready: "Готово", building: "Компиляция…", running: "Выполняется…", couldNotBuild: "Не удалось скомпилировать.",
      correct: "Верно!", wrong: "Вывод не совпадает с ожидаемым.", expected: "Ожидалось", got: "Ваш вывод", answer: "Правильный ответ",
      contents: "Содержание", badges: "Значки", progress: "Прогресс", lessons: "уроков",
      b_first_run: "Первая программа", b_first_ex: "Первое упражнение", b_ex10: "10 упражнений", b_quiz5: "5 верных ответов", b_chapter: "Глава завершена",
      cont: "Продолжить с того места, где остановились", start: "Начать", review: "Рекомендуем сначала завершить этот урок",
      localOnly: "Этот пример не запускается в браузере; попробуйте его на своём компьютере.",
      ref: "Справочник стандартной библиотеки", search: "Поиск: функция, тип, модуль…", modules: "Модули", results: "результатов", noResults: "Ничего не найдено.",
      openInEditor: "Попробовать в редакторе", finishNeeds: "Нужно для завершения", stopped: "Остановлено.", tooLong: "Программа работала слишком долго.", exit: "код выхода"
    },
    zh: {
      title: "学习 Greengold", lede: "从零开始，直到标准库。在浏览器里写代码、运行它、完成练习。",
      pickPath: "选择你的路径", beginner: "我是编程新手", dev: "我会其他语言",
      pathNote: "程序员路径会跳过“编程入门”课程。", skipped: "已跳过",
      run: "运行", stop: "停止", reset: "重置", check: "检查", hint: "提示", solution: "显示答案",
      tryIt: "试一试", exercise: "练习", openEx: "在编辑器中打开", quiz: "问题", next: "下一课", prev: "上一课", done: "完成",
      loading: "加载中…", ready: "就绪", building: "编译中…", running: "运行中…", couldNotBuild: "编译失败。",
      correct: "正确！", wrong: "输出与预期不符。", expected: "预期", got: "你的输出", answer: "正确答案",
      contents: "目录", badges: "徽章", progress: "进度", lessons: "课",
      b_first_run: "第一个程序", b_first_ex: "第一个练习", b_ex10: "10 个练习", b_quiz5: "5 个正确答案", b_chapter: "完成一章",
      cont: "从上次停下的地方继续", start: "开始", review: "建议先完成这一课",
      localOnly: "此示例无法在浏览器中运行；请在你自己的电脑上试试。",
      ref: "标准库参考", search: "搜索：函数、类型、模块……", modules: "模块", results: "条结果", noResults: "没有结果。",
      openInEditor: "在编辑器中试用", finishNeeds: "完成所需", stopped: "已停止。", tooLong: "程序运行时间过长。", exit: "退出码"
    }
  }
};
