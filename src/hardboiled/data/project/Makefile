# Proyecto hardboiled: `make`, `make run`, `make headless`, `make clean`.
SRCS    := $(wildcard *.c)
HEADERS := $(wildcard *.h)
TARGET  := {name}.elf

all: $(TARGET)

$(TARGET): $(SRCS) $(HEADERS)
	hardboiled build $(SRCS) -o $@

run: $(TARGET)
	hardboiled run $(TARGET)

headless: $(TARGET)
	hardboiled run $(TARGET) --headless

clean:
	rm -f $(TARGET)

.PHONY: all run headless clean
