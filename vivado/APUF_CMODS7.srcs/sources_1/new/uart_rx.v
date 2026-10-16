module uart_rx #(
    parameter CLK_FREQ = 12000000,
    parameter BAUD     = 115200
)(
    input  wire clk,
    input  wire rst,
    input  wire rx,
    output reg [7:0] data,
    output reg valid
);
    localparam DIV = CLK_FREQ / BAUD;

    reg [15:0] counter = 0;
    reg [3:0]  bitpos  = 0;
    reg [9:0]  shift   = 10'h3FF;
    reg busy = 0;

    always @(posedge clk) begin
        if (rst) begin
            valid   <= 0;
            busy    <= 0;
            counter <= 0;
            bitpos  <= 0;
            data    <= 0;
        end else begin
            valid <= 0; // Default state is 0 (pulse)
            
            if (!busy) begin
                if (rx == 0) begin // Start bit detected
                    busy    <= 1;
                    counter <= DIV/2; // Sample in the middle of the bit
                    bitpos  <= 0;
                end
            end else begin
                if (counter == DIV-1) begin
                    counter <= 0;
                    shift[bitpos] <= rx;
                    bitpos  <= bitpos + 1;

                    if (bitpos == 9) begin
                        busy  <= 0;
                        data  <= shift[8:1];
                        valid <= 1; // Pulse valid for 1 clock cycle
                    end
                end else begin
                    counter <= counter + 1;
                end
            end
        end
    end

endmodule
