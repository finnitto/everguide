"""Export the four editable review tabs back to CSV for validation."""
from pathlib import Path
import argparse, csv
from openpyxl import load_workbook
ROOT=Path(__file__).parent
MAP={
    'Provider Review':'provider_verification_register.csv',
    'Branch Review':'branch_verification_register.csv',
    'Evidence Log':'evidence_log.csv',
    'Decision Log':'decision_log.csv',
}
def main():
    p=argparse.ArgumentParser(); p.add_argument('--workbook',type=Path,default=ROOT/'thurrock_verification_workbook.xlsx'); p.add_argument('--out',type=Path,default=ROOT)
    a=p.parse_args(); wb=load_workbook(a.workbook,read_only=True,data_only=True); a.out.mkdir(parents=True,exist_ok=True)
    for sheet,filename in MAP.items():
        ws=wb[sheet]; iterator=ws.iter_rows(values_only=True)
        headers=next(iterator)
        with (a.out/filename).open('w',newline='',encoding='utf-8-sig') as f:
            writer=csv.DictWriter(f,fieldnames=list(headers)); writer.writeheader()
            for values in iterator:
                if not any(v is not None and str(v).strip() for v in values): continue
                writer.writerow({headers[i]: ('' if v is None else v) for i,v in enumerate(values)})
        print(f'Exported {sheet} -> {a.out/filename}')
if __name__=='__main__': main()
