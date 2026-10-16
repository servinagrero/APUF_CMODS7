module uart_tx #(
    parameter CLK_FREQ = 12000000,
    parameter BAUD     = 115200
)(
    input  wire clk,
    input  wire rst,
    input  wire [7:0] data,
    input  wire start,
    output reg tx,
    output reg busy
);
    localparam DIV = CLK_FREQ / BAUD;

    reg [15:0] counter = 0;
    reg [3:0] bitpos = 0;
    reg [9:0] shift;

    initial tx = 1'b1;

    always @(posedge clk) begin
        if (rst) begin
            tx      <= 1'b1;
            busy    <= 0;
            counter <= 0;
            bitpos  <= 0;
        end else begin
            if (!busy) begin
                if (start) begin
                    busy    <= 1;
                    shift   <= {1'b1, data, 1'b0};
                    bitpos  <= 0;
                    counter <= 0;
                end
            end else begin
                if (counter == DIV-1) begin
                    counter <= 0;
                    tx      <= shift[bitpos];
                    bitpos  <= bitpos + 1;

                    if (bitpos == 9) begin
                        busy <= 0;
                        tx   <= 1'b1;
                    end
                end else begin
                    counter <= counter + 1;
                end
            end
        end
    end

endmodule
