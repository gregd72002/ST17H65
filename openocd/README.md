# SWD programming 

Pin 2 and Pin 3 on the ST17H65 are exposed as prong pads. Just above the middle button on the PCB.

However I was not able to get the conneciton established.

The config assumes RPi host.

```
    openocd \
      -f ./st17h65-swd.cfg \
      -c "transport select swd" \
      -c "adapter speed 10" \
      -f ./st17h65.cfg
```

